#/opt/CSCperl/current/bin/perl
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
# getItemIds.cgi script fetches the item ids related to the given holdings record.
#

use strict;
use CGI;
use DBI;
use POSIX;
use Cwd 'abs_path';
use File::Basename 'dirname';

my $base_path = dirname(abs_path($0)) . '/';
my $config_file = $base_path . 'get_item_ids.conf';

my %config = ();
my %ip_config = ();

# Database
my $db_params = 'host=localhost;SID=VGER';
my $dbh = undef;
my $ora_home = read_env_file();

$ENV{ORACLE_HOME} = "$ora_home";

################
#    MAIN      #
################

read_config($config_file);
read_ip_config($base_path . $config{'general'}{'ip config file'});

writelog('info', 'Starting getItemIds.cgi');

# Check if IP is valid
my $ip_addr = $ENV{'REMOTE_ADDR'};
if(!is_ip_allowed($ip_addr)) {
  writelog('warn', 'Request not processed. Access denied');
  send_http_error('401');
  writelog('info', 'Exit program');
  exit (1);
}

my %request_parameters = parse_request_parameters();

# Check that bibId parameter exists
# and contains only numbers
if(!check_bib_id()) {
    writelog('warn', 'Request not processed. No bib id parameter found');
    send_http_error('405');
    writelog('info', 'Exit program');
    exit (1);
}

my $response = get_ids($request_parameters{'mfhdId'});

if(length($response) == 0) {
  writelog('info', 'No record found');
  send_http_error('404');
  writelog('info', 'Exit program');
  exit (0);
}

send_http_header();
writelog('info', 'Sending response');
print $response;
writelog('info', 'Done! Exiting');

exit(0);
####################################
sub get_ids($) {
  my($mfhd_id) = @_;
  my $response_str;

  open_db_connection();
  my @ids = get_item_ids($mfhd_id);
  close_db_connection();

  if(@ids ==0) {
    return $response_str;
  }

  writelog('info', 'Starting to create XML for output');

  $response_str .= get_xml_header();

  for my $id (@ids) {
    $response_str .= "  <itemId>$id</itemId>\n";
  }
  $response_str .= get_xml_footer();
  if(@ids == 0) {
    $response_str =~ s/<itemIds>\n<\/itemIds>/<itemIds \/>/;
  }
  writelog('info', 'Creating XML done');
  
  return $response_str;
}
####################################
sub get_item_ids($) {
  my ($mfhd_id) = @_;
  my $sql = "
    SELECT item_id 
    FROM $config{'db'}{'dbname'}.mfhd_item
    WHERE mfhd_id = $mfhd_id
  ";

  writelog('info', "Fetching item ids related to the given mfhd id from DB. Mfhd id: $mfhd_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
    or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
    or die DateTime() . "|" . $dbh->errstr;

  my @ids = ();
  while( my($id) = $sth->fetchrow_array())
  {
    push(@ids, $id);
  }
  $sth->finish();
  writelog('debug', "Found " . @ids . " id(s): @ids");
  return @ids;
}
####################################
sub get_xml_header() {
  my $response = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
  $response .= "<itemIds>\n";
  return $response;
}
####################################
sub get_xml_footer() {
  return "</itemIds>\n";
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
  my $db_username = "ro_" . $config{'db'}{'dbname'} . "db";
  my $db_passwd = "ro_" . $config{'db'}{'dbname'} . "db";

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
sub check_bib_id() {
  writelog('debug', 'Checking request parameters');
  if(exists($request_parameters{'mfhdId'})) {
    writelog('debug', 'Mfhd id found');
    if($request_parameters{'mfhdId'} =~ m/^[0-9]+$/) {
      writelog('debug', 'Mfhd id contains only numbers');
      return 1;
    }
    writelog('info', "Bad formed mfhd id: $request_parameters{'mfhdId'}");
    return 0;
  }
  writelog('info', 'No mfhd id found');
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
