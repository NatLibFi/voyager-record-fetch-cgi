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
# Fetches settings needed by the Cataloging client from Voyager database. Settings are user dependent so username name must be supplied with the request. Returns the response as XML.
#
 
use strict;
use CGI;
use DBI;
use POSIX;
use Cwd 'abs_path';
use File::Basename 'dirname';

my $base_path = dirname(abs_path($0)) . '/';
my $config_file = $base_path . 'get_settings.conf';

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

writelog('info', 'Starting getSettings.pl');

# Check if IP is valid
my $ip_addr = $ENV{'REMOTE_ADDR'};
if(!is_ip_allowed($ip_addr)) {
  writelog('warn', 'Request not processed. Access denied');
  send_http_error('401');
  writelog('info', 'Exit program');
  exit (1); 
}

my %request_parameters = parse_request_parameters();

# Check that user parameter exists
if(!check_user()) {
  writelog('warn', 'Request not processed. No user parameter found');
  send_http_error('405');
  writelog('info', 'Exit program');
  exit (1);
}

my $response = get_settings($request_parameters{'user'});

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
# Subs starting from here.
####################################
sub get_settings($) {
  my($user) = @_;
  my @cat_locs = ();
  my @locs = ();
  my @item_types = ();
  my @item_status_types = ();
  my @media_types = ();
  my @action_types = ();

  my $response_str;

  open_db_connection();
  @cat_locs = get_cat_locs($user);
  @locs = get_locs($user);
  @item_types = get_item_types();
  @item_status_types = get_item_status_types();
  @media_types = get_media_types();
  @action_types = get_action_types();
  close_db_connection();

  if(@cat_locs ==0) {
    return $response_str;
  }

  writelog('info', 'Starting to create XML for output');

  $response_str .= get_xml_header();

  if(@cat_locs > 0) {
    writelog('debug', 'Adding cataloging locations');
    $response_str .= get_indent(1) . "<catalogingLocations>\n";
    for my $cat_loc (@cat_locs) {
      $response_str .= convert_cat_loc_to_xml(\@$cat_loc);
    }
    $response_str .= get_indent(1) . "</catalogingLocations>\n";
  } else {
    $response_str .= get_indent(1) . "<catalogingLocations/>\n";
  }

  if(@locs > 0) {
    writelog('debug', 'Adding locations');
    $response_str .= get_indent(1) . "<locations>\n";
    for my $loc (@locs) {
      $response_str .= convert_loc_to_xml(\@$loc);
    }
    $response_str .= get_indent(1) . "</locations>\n";
  } else {
    $response_str .= get_indent(1) . "<locations/>\n";
  }

  if(@item_types > 0) {
    writelog('debug', 'Adding item types');
    $response_str .= get_indent(1) . "<itemTypes>\n";
    for my $type (@item_types) {
      $response_str .= convert_item_type_to_xml(\@$type);
    }
    $response_str .= get_indent(1) . "</itemTypes>\n";
  } else {
    $response_str .= get_indent(1) . "<itemTypes/>\n";
  }

  if(@item_status_types > 0) {
    writelog('debug', 'Adding item status types');
    my %sys_statuses = get_sys_applied_item_statuses();
    $response_str .= get_indent(1) . "<itemStatusTypes>\n";
    for my $type (@item_status_types) {
      $response_str .= convert_item_status_type_to_xml(\@$type, \%sys_statuses);
    }
    $response_str .= get_indent(1) . "</itemStatusTypes>\n";
  } else {
    $response_str .= get_indent(1) . "<itemStatusTypes/>\n";
  }

  if(@media_types > 0) {
    writelog('debug', 'Adding media types');
    $response_str .= get_indent(1) . "<mediaTypes>\n";
    for my $type (@media_types) {
      $response_str .= convert_media_type_to_xml(\@$type);
    }
    $response_str .= get_indent(1) . "</mediaTypes>\n";
  } else {
    $response_str .= get_indent(1) . "<mediaTypes/>\n";
  }

  if(@action_types > 0) {
    writelog('debug', 'Adding action types');
    $response_str .= get_indent(1) . "<actionTypes>\n";
    for my $type (@action_types) {
      $response_str .= convert_action_type_to_xml(\@$type);
    }
    $response_str .= get_indent(1) . "</actionTypes>\n";
  } else {
    $response_str .= get_indent(1) . "<actionTypes/>\n";
  }

  $response_str .= get_xml_footer();
  writelog('info', 'Creating XML done');

  return $response_str;
}
####################################
sub convert_cat_loc_to_xml($$) {
  my ($location) = @_;
  my $fields = get_indent(2) . "<catalogingLocation>\n";
  my $spacing = get_indent(3);

  utf8::encode(@{$location}[1]);
  utf8::encode(@{$location}[3]);
  utf8::encode(@{$location}[5]);

  $fields .= "$spacing<locationId>@{$location}[0]</locationId>\n";
  $fields .= "$spacing<locationName>" . escape_xml(@{$location}[1]) . "</locationName>\n";
  $fields .= "$spacing<libraryId>@{$location}[2]</libraryId>\n";
  $fields .= "$spacing<libraryDisplayName>" . escape_xml(@{$location}[3]) . "</libraryDisplayName>\n";
  $fields .= "$spacing<defaultItemType>@{$location}[4]</defaultItemType>\n";
  $fields .= "$spacing<itemTypeName>" . escape_xml(@{$location}[5]) . "</itemTypeName>\n";

  $fields .= get_indent(2) . "</catalogingLocation>\n";

  return $fields;
}
####################################
sub convert_loc_to_xml($) {
  my ($location) = @_;
  my $fields = get_indent(2) . "<location>\n";
  my $spacing = get_indent(3);

  utf8::encode(@{$location}[1]);
  utf8::encode(@{$location}[2]);

  $fields .= "$spacing<locationId>@{$location}[0]</locationId>\n";
  $fields .= "$spacing<locationCode>" . escape_xml(@{$location}[1]) . "</locationCode>\n";
  $fields .= "$spacing<locationName>" . escape_xml(@{$location}[2]) . "</locationName>\n";

  $fields .= get_indent(2) . "</location>\n";

  return $fields;
}
####################################
sub convert_item_type_to_xml($) {
  my ($type) = @_;
  my $fields = get_indent(2) . "<itemType>\n";
  my $spacing = get_indent(3);

  utf8::encode(@{$type}[1]);

  $fields .= "$spacing<itemTypeId>@{$type}[0]</itemTypeId>\n";
  $fields .= "$spacing<itemTypeName>" . escape_xml(@{$type}[1]) . "</itemTypeName>\n";

  $fields .= get_indent(2) . "</itemType>\n";

  return $fields;
}
####################################
sub convert_item_status_type_to_xml($$) {
  my ($type, $sys_statuses) = @_;
  my $system = ' systemStatus="false"';

  if( defined($$sys_statuses{@{$type}[0]}) ) {
    $system = ' systemStatus="true"';
  }

  my $fields = get_indent(2) . "<itemStatusType".$system.">\n";
  my $spacing = get_indent(3);

  utf8::encode(@{$type}[1]);

  $fields .= "$spacing<itemStatusTypeId>@{$type}[0]</itemStatusTypeId>\n";
  $fields .= "$spacing<itemStatusDesc>" . escape_xml(@{$type}[1]) . "</itemStatusDesc>\n";
  $fields .= get_indent(2) . "</itemStatusType>\n";

  return $fields;
}
####################################
sub convert_media_type_to_xml($$) {
  my ($type) = @_;
  my $fields = get_indent(2) . "<mediaType>\n";
  my $spacing = get_indent(3);

  utf8::encode(@{$type}[1]);

  $fields .= "$spacing<mediaTypeId>@{$type}[0]</mediaTypeId>\n";
  $fields .= "$spacing<typeCode>" . escape_xml(@{$type}[1]) . "</typeCode>\n";

  $fields .= get_indent(2) . "</mediaType>\n";

  return $fields;
}
###################################
sub convert_action_type_to_xml($) {
    my ($type) = @_;
    my $fields = get_indent(2) . "<actionType>\n";
    my $spacing = get_indent(3);

    utf8::encode(@{$type}[1]);

    $fields .= "$spacing<actionTypeId>@{$type}[0]</actionTypeId>\n";
    $fields .= "$spacing<actionTypeDesc>" . escape_xml(@{$type}[1]) . "</actionTypeDesc>\n";

    $fields .= get_indent(2) . "</actionType>\n";

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
  writelog('debug', 'Adding XML header');
  my $response = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
  $response .= "<voyagerSettings>\n";
  return $response;
}
####################################
sub get_xml_footer() {
  writelog('debug', 'Adding XML footer');
  return "</voyagerSettings>\n";
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
sub get_sys_applied_item_statuses() {
  my %hash = ();
  writelog('debug', 'Get system applied item statuses');
  if(defined($config{'general'}{'sys applied item status'})) {
    my $temp = $config{'general'}{'sys applied item status'};
    writelog('debug', "System applier item statuses: $temp");
    $temp =~ s/\s*//g;
    my @arr = split /,/, $temp;
    for my $par ( @arr ) { $hash{$par} = 1; }
    $config{'general'}{'sys applied item status'} = %hash;
  }
  return %hash;
}
####################################
sub open_db_connection() {
  my $db_username = "ro_" . $config{'db'}{'dbname'} . "db";
  my $db_passwd = "ro_" . $config{'db'}{'dbname'} . "db";

  writelog('debug', 'Opening database connection');
  $dbh = DBI->connect(
    "dbi:Oracle:$db_params",
    $db_username,
    $db_passwd);
  
  if(!$dbh) {
    writelog('error', "Could not connect: $DBI::errstr"); 
    die ("Could not connect: $DBI::errstr");
  }

  $dbh->{LongReadLen} = 10000;
  $dbh->{LongTruncOk} = 1;
}
####################################
sub close_db_connection() {
  if($dbh) {
    writelog('debug', 'Closing database connection');
    $dbh->disconnect();
  }
}
####################################
sub get_cat_locs($) {
  my ($user) = @_;
  my $sql = "
    SELECT csl.location_id, l.location_name, l.library_id,
      li.library_display_name, cpl.default_item_type, it.item_type_name
    FROM $config{'db'}{'dbname'}.cat_operator co, $config{'db'}{'dbname'}.cat_security_locs csl, $config{'db'}{'dbname'}.location l, $config{'db'}{'dbname'}.library li,
      $config{'db'}{'dbname'}.cat_policy_locs cpl, $config{'db'}{'dbname'}.item_type it
    WHERE co.cat_profile_id = csl.cat_profile_id 
      AND csl.location_id = l.location_id
      AND cpl.location_id = csl.location_id
      AND l.library_id = li.library_id
      AND cpl.default_item_type = it.item_type_id
      AND cpl.cataloging_location = 'Y'
      AND co.operator_id = '$user'
     ORDER BY l.location_name
  ";

  writelog('info', "Fetching cataloging locations from DB. User: $user");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @locations = ();
  while( my(@location) = $sth->fetchrow_array())
  {
    push @locations, [ @location ];
  }
  $sth->finish();
  writelog('debug', "Found " . @locations . " cataloging location(s)");
  return @locations;
}
####################################
sub get_locs($) {
  my ($user) = @_;
  my $sql = "
    SELECT l.location_id, l.location_code, l.location_name
    FROM $config{'db'}{'dbname'}.cat_operator co, $config{'db'}{'dbname'}.cat_security_locs csl, $config{'db'}{'dbname'}.location l
    WHERE co.cat_profile_id = csl.cat_profile_id 
      AND csl.location_id = l.location_id
      AND co.operator_id = '$user'
    ORDER BY l.location_name
  ";

  writelog('info', "Fetching locations from DB. User: $user");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @locations = ();
  while( my(@location) = $sth->fetchrow_array())
  {
      push @locations, [ @location ];
  }
    $sth->finish();
    writelog('debug', "Found " . @locations . " location(s)");
    return @locations;
}
####################################
sub get_item_types() {
  my $sql = "
    SELECT it.item_type_id, it.item_type_name
    FROM $config{'db'}{'dbname'}.item_type it
    ORDER BY it.item_type_name
  ";

  writelog('info', "Fetching item types from DB");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @types = ();
  while( my(@type) = $sth->fetchrow_array())
  {
      push @types, [ @type ];
  }
    $sth->finish();
    writelog('debug', "Found " . @types . " item type(s)");
    return @types;
}
####################################
sub get_item_status_types() {
  my $sql = "
    SELECT item_status_type, item_status_desc
    FROM $config{'db'}{'dbname'}.item_status_type
    ORDER BY item_status_desc
  ";

  writelog('info', "Fetching item status types from DB");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @types = ();
  while( my(@type) = $sth->fetchrow_array())
  {
      push @types, [ @type ];
  }
  $sth->finish();
  writelog('debug', "Found " . @types . " item status type(s)");
  return @types;
}
####################################
sub get_media_types() {
  my $sql = "
    SELECT media_type_id, type_code, type
    FROM $config{'db'}{'dbname'}.media_type
    ORDER BY type
  ";

  writelog('info', "Fetching media types from DB");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @types = ();
  while( my(@type) = $sth->fetchrow_array())
  {
    push @types, [ @type ];
  }
  $sth->finish();
  writelog('debug', "Found " . @types . " media type(s)");
  return @types;
}
####################################
sub get_action_types() {
  my $sql = "
    SELECT action_type_id, action_type
    FROM $config{'db'}{'dbname'}.action_type
  ";

  writelog('info', "Fetching action types from DB");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @types = ();
  while( my(@type) = $sth->fetchrow_array())
  {
    push @types, [ @type ];
  }
  $sth->finish();
  writelog('debug', "Found " . @types . " action type(s)");
  return @types;
}
####################################
sub send_http_header() {
  writelog('debug', 'Sending http header');
  print "Content-Type: text/xml\n\n";    
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
    '404', 'User not found',
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
sub check_user() {
  writelog('debug', 'Checking request parameters');
  if(exists($request_parameters{'user'})) {
    writelog('debug', 'User found');
    if($request_parameters{'user'} =~ m/^\w+$/) {
      writelog('debug', 'User parameter ok');
      return 1;
    }
    writelog('info', "Bad formed user: $request_parameters{'bibId'}");
    return 0;
  }
  writelog('info', 'No user found');
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
