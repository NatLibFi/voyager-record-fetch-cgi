#!/opt/CSCperl/current/bin/perl
#
# Copyright 2017 University Of Helsinki (The National Library Of Finland)
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Fetches a list of headings matching the given conditions. Returns the response as XML.
# Parameters:
# type: N=Name, E=Name-Title, T=Title, S=Subject
# query: query string
#

use strict;
use CGI '-utf8';
use DBI;
use POSIX;
use Cwd 'abs_path';
use File::Basename 'dirname';
use Unicode::Normalize qw(NFC compose NFD decompose);
use URI::Escape;
use Encode;

my $base_path = dirname(abs_path($0)) . '/';
my $config_file = $base_path . 'get_headings.conf';

my %config = ();
my %ip_config = ();

# Database
my $db_params = 'host=localhost;SID=VGER';
my $dbh = undef;
my $ora_home = read_env_file();

$ENV{ORACLE_HOME} = "$ora_home";
$ENV{NLS_LANG} = "AMERICAN.US7ASCII";

################
#    MAIN      #
################

read_config($config_file);
read_ip_config($base_path . $config{'general'}{'ip config file'});

writelog('info', "Starting getHeadings.pl");

# Check if IP is valid
my $ip_addr = $ENV{'REMOTE_ADDR'};
if(!is_ip_allowed($ip_addr)) {
  writelog('warn', 'Request not processed. Access denied');
  send_http_error('401');
  writelog('info', 'Exit program');
  exit (1); 
}

my %request_parameters = parse_request_parameters();

# Check that recordId and recordType parameters exist.
# RecordId can contain only numbers.
# RecordType must be bib/mfhd/item, otherwise the value is invalid.
if(!check_query_string() || !check_type()) {
  writelog('warn', 'Request not processed. Invalid or missing parameters');
  send_http_error('405');
  writelog('info', 'Exit program');
  exit (1);
}

my $response = get_headings($request_parameters{'query'}, $request_parameters{'type'});

if(length($response) == 0) {
  writelog('info', 'No record found');
  send_http_error('404');
  writelog('info', 'Exit program');
  exit (0);
}

#a hack to tell perl that the data is unicode
$response = pack("U0C*", unpack ("C*", $response));

#normalize to composed utf8
$response = NFC($response); 

binmode STDOUT, ':utf8';
send_http_header();
writelog('info', 'Sending response');
print $response;
writelog('info', 'Done! Exiting');

exit(0);

####################################
# Subs starting from here.
####################################
sub get_headings($$) {
  my($query, $type) = @_;
  my @results = ();
  my $response_str;

  open_db_connection();
  @results = fetch_headings();

  for(my $i=0; $i < scalar(@results); $i++) { 
    my @auth_ids = fetch_auth_ids($results[$i][0]);
    for(my $j=0; $j < scalar(@auth_ids); $j++) {
      if($auth_ids[$j][2] == 0) {
        $auth_ids[$j][4] = fetch_heading($auth_ids[$j][1]);
      } else {
        $auth_ids[$j][4] = fetch_heading($auth_ids[$j][2]);
      }
    }
    push @{$results[$i]}, [ @auth_ids ];
  }

  close_db_connection();
  if(@results == 0) {
    return $response_str;
  }

  writelog('info', 'Starting to create XML for output');
  $response_str .= get_xml_header();
  for my $heading (@results) {
    $response_str .= heading_to_xml(\@$heading);
  }
  $response_str .= get_xml_footer();
  writelog('info', 'Creating XML done');

  return $response_str;
}
####################################
sub fetch_headings() {
  my $query = $request_parameters{'query'};
  my $type = $request_parameters{'type'};

  my $sql = "
    SELECT h.heading_id, h.display_heading, h.staffbibs, h.staffrefs, ht.heading_type_desc
    FROM $config{'db'}{'dbname'}db.heading h, $config{'db'}{'dbname'}db.index_type it, $config{'db'}{'dbname'}db.heading_type ht
    WHERE h.index_type = it.index_type
      AND h.heading_type = ht.heading_type
      AND h.index_type = ht.index_type
      AND lower(h.display_heading) like lower('$query') 
      AND h.index_type = '$type'
    ORDER BY h.display_heading
  ";

  writelog('info', "Fetching headings from DB. Query string: '$request_parameters{'query'}'. Type: $request_parameters{'type'}.");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @headings = ();
  while( my(@heading) = $sth->fetchrow_array())
  {
    push @headings, [ @heading ];
  }
  $sth->finish();
  writelog('debug', "Found " . @headings . " heading(s)");
  return @headings;
}
####################################
sub fetch_auth_ids($) {
  my($heading_id) = @_;
  
  my $sql = "
   SELECT ah.auth_id, ah.heading_id_pointer, ah.heading_id_pointee, rt.reference_type_desc
   FROM $config{'db'}{'dbname'}db.auth_heading ah, $config{'db'}{'dbname'}db.reference_type rt
   WHERE ah.reference_type = rt.reference_type
     AND ah.heading_id_pointer = $heading_id
  ";

  writelog('info', "Fetching auth ids from DB. Heading id: $heading_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @ids = ();
  while( my(@id) = $sth->fetchrow_array())
  {
    push @ids, [ @id ];
  }
  $sth->finish();
  writelog('debug', "Found " . @ids . " auth id(s)");
  return @ids;
}
####################################
sub fetch_heading($) {
  my($heading_id) = @_;

  my $sql = "
   SELECT distinct h.display_heading
   FROM $config{'db'}{'dbname'}db.heading h
   WHERE h.heading_id = $heading_id
  ";

  writelog('info', "Fetching heading from info DB. Heading id: $heading_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my $heading = 0;
  if( my($temp) = $sth->fetchrow_array())
  {
    $heading = $temp;
  }
  $sth->finish();

  if($heading == 0) {
    writelog('debug', "Found heading: $heading");
  } else {
    writelog('debug', "No matching headings found");
  }

  return $heading;
  
}
####################################
sub heading_to_xml($) {
  my ( $heading) = @_;
  my $fields = get_indent(1) . "<heading>\n";
  my $spacing = get_indent(2);

  if(defined($config{'ref_types'}{lc(@{$heading}[3])})) {
    $fields .= "$spacing<referenceTypeDesc>".$config{'ref_types'}{lc(@{$heading}[3])}."</referenceTypeDesc>\n";
  } else {
    $fields .= "$spacing<referenceTypeDesc />\n";
  }
  $fields .= "$spacing<displayHeading>@{$heading}[1]</displayHeading>\n";
  $fields .= "$spacing<staffBibsCount>@{$heading}[2]</staffBibsCount>\n";
  $fields .= "$spacing<headingTypeDesc>@{$heading}[4]</headingTypeDesc>\n";

  my $column_5 = @{$heading}[5];
  if(scalar(@{$column_5}) == 0) {
    $fields .= get_indent(2) . "<authorityRecs />\n";
  } else {
    $fields .= get_indent(2) . "<authorityRecs>\n";
    foreach my $rec (@{$column_5}) {
      $fields .= get_indent(3) . "<authorityRec>\n";
      $fields .= get_indent(4) . "<authorityId>@{$rec}[0]</authorityId>\n";
      $fields .= get_indent(4) . "<authorityHeading>@{$rec}[4]</authorityHeading>\n";
      $fields .= get_indent(4) . "<referenceType>@{$rec}[3]</referenceType>\n";
      $fields .= get_indent(3) . "</authorityRec>\n";
    }
    $fields .= get_indent(2) . "</authorityRecs>\n";
  }
  $fields .= get_indent(1) . "</heading>\n";
  return $fields;
}
####################################
sub escape_xml($) {
  my ($str) = @_;

  return '' if (!defined($str));

  $str =~ s/\&/\&amp;/g;
  $str =~ s/</\&lt;/g;
  $str =~ s/>/\&gt;/g;
  $str =~ s/\x1f/ /g;
  
  return $str;
}
####################################
sub get_xml_header() {
  my $response = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
  $response .= "<headings>\n";
  return $response;
}
####################################
sub get_xml_footer() {
  return "</headings>\n";
}
####################################
sub get_indent($) {
  my($level) = @_;
  my $limit = $level * $config{'general'}{'indent'};
  my $response = "";
  for(my $i=0; $i < $limit; $i++) {
     $response .= " ";
  }
  return $response;
}
####################################
sub read_config($)
{
  my ($config_file) = @_;
  my $section;
  my $fh;
  open($fh, "<$config_file") || die("Could not open configuration file $config_file for reading: $!");

  while (my $orig_line = <$fh>)
  {
    my $line = $orig_line;
    $line =~ s/\s*#.*$//g;
    $line =~ s/^\s*(.*)\s*$/$1/;
    $line =~ s/\s*=\s*/=/g;
    if (!$line) {
      next;
    }

    if ($line =~ /^\[([^\s]+)\]/) {
      $section = $1;
      next;
    }

    if ($line =~ /([\w\s]+?)=(.*)/) {
      $config{$section}{lc($1)} = $2;
    } else {
      die ("Invalid configuration file line: $orig_line");
    }
  }
  close($fh);
}
####################################
sub read_ip_config($)
{
  my ($ip_config_file) = @_;
  my $section;
  my $fh;
  open($fh, "<$ip_config_file") || die("Could not open ip configuration file $ip_config_file for reading: $!");

  while (my $orig_line = <$fh>)
  {
    my $line = $orig_line;
    $line =~ s/\s*#.*$//g;
    $line =~ s/^\s*(.*)\s*$/$1/;
    
    if (!$line) {
      next;
    }

    if ($line =~ /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/) {
      $ip_config{$line} = 1;
    } else {
      die ("Invalid configuration file line: $orig_line");
    }
  }
  close($fh);
}
####################################
sub read_env_file() {
  my $oracle_home = "";
  my $env_file = $base_path;
  $env_file =~ /(\/m1\/voyager\/\w+db)\/.+/;
    $env_file = "$1/ini/voyager.env";

    my $fh;
    open($fh, "<$env_file") || die("Could not open voyager.env file $env_file for reading: $!");

  while (my $line = <$fh>)
  {
    chomp($line);
    if ( $line =~ /^\s*export\s+ORACLE_HOME\s*=\s*(\S+)/ ) {
      $oracle_home = $1;
      last;
    }
  }
  close($fh);
  return $oracle_home;
}
####################################
sub open_db_connection() {
  my $db_username = "ro_" . $config{'db'}{'dbname'}db.. "db";
  my $db_passwd = "ro_" . $config{'db'}{'dbname'}db.. "db";

  writelog('debug', 'Opening database connection');
  $dbh = DBI->connect(
    "dbi:Oracle:$db_params",
    $db_username,
    $db_passwd
  );
  
  if(!$dbh) {
    writelog('error', "Could not connect: $DBI::errstr"); 
    die ("Could not connect: $DBI::errstr");
  }
}
####################################
sub close_db_connection() {
  if($dbh) {
    writelog('debug', 'Closing database connection');
    $dbh->disconnect();
  }
}
####################################
sub send_http_header() {
  writelog('debug', 'Sending http header');
  print "Content-Type: text/xml; charset=UTF-8\n\n";    
}
####################################
sub send_http_error($)
{
  my ($error_code) = @_;

  my %errorname = (
    '401', 'Forbidden',
    '404', 'Not Found',
    '405', 'Method Not Allowed'
      );
  my %errordesc = (
    '401', 'Access denied',
    '404', 'Record not found',
    '405', 'Not allowed'
      );

  writelog('debug', "Sending http error $error_code: $errordesc{$error_code}");

  printf("Status: %s %s\n", $error_code, $errorname{$error_code});
  printf("Content-Type: text/xml; charset=UTF-8\n\n");
  printf("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
  printf("%s\n", "<error>".$errordesc{$error_code}."</error>");
}
####################################
sub is_ip_allowed($) {
  writelog('debug', 'Validating IP address');
  my($ip) = @_;
  if(exists($ip_config{$ip})) {
    writelog('info', "IP address validated succesfully: $ip");
    return 1;
  }
  writelog('info', "IP address blocked: $ip");
  return 0;
}
####################################
sub parse_request_parameters() {
  writelog('debug', 'Parsing request parameters');
  my $query_str = $ENV{'QUERY_STRING'};
  my %parameters = ();

  foreach(split(/&/,$query_str)) {
    (my $key, my $value) = split(/=/);
    $parameters{$key} = $value;
  }
  return %parameters;
}
####################################
sub check_query_string() {
  writelog('debug', 'Checking request parameters');
  if(exists($request_parameters{'query'})) {
    $request_parameters{'query'} = uri_unescape ($request_parameters{'query'});
    $request_parameters{'query'} = decode('utf-8',$request_parameters{'query'});
    writelog('debug', "Query string found: $request_parameters{'query'}");
    return 1;
  }
  writelog('info', 'No query string found');
  return 0;
}
###################################
sub check_type() {
  writelog('debug', 'Checking request parameters');
  if(exists($request_parameters{'type'})) {
	  writelog('debug', 'Type parameter found...validating value...');
    $request_parameters{'type'} = uc( $request_parameters{'type'} );
	  if($request_parameters{'type'} =~ m/^(N|E|T|S)$/) {
	    writelog('debug', "Valid type detected: $request_parameters{'type'}");
	    return 1;
	  }
	  writelog('info', "Invalid type: $request_parameters{'type'}");
	  return 0;
  }
  writelog('info', 'No type found');
  return 0;
}
####################################
sub writelog($$)
{
  my ($level, $str) = @_;

  if(!check_log_level($level)) {
    return;
  }
  
  my ($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = localtime(time);
  my $date = sprintf($config{'logging'}{'date time format'},($year + 1900),($mon+1),$mday,$hour,$min,$sec);

  my $msg;
  $msg = sprintf("[%s] - %d - [ %s ] - %s\n", $date, $$, (uc $level), $str);

  my $fh;
  if(!open ($fh, ">>$base_path$config{'logging'}{'file'}"))
  {
    die ("Could not open log file for appending: $!");
  }
  else
  {
    print $fh $msg;
    close($fh);
  }
}
####################################
sub check_log_level($) {
  my ($level) = @_;
  my $sys_level = $config{'logging'}{'level'};
  if(log_level_to_number($level) >= log_level_to_number($sys_level)) {
    return 1;
  } 
  return 0;
}
####################################
sub log_level_to_number($) {
  my ($level) = @_;
  if($level =~ m/^debug$/i) {
    return 1;
  } elsif($level =~ m/^info$/i) {
    return 2;
  } elsif($level =~ m/^warn$/i) {
    return 3;
  } elsif($level =~ m/^error$/i) {
    return 4;
  }
  return 0;
}
