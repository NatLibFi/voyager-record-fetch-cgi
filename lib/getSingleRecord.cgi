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
# Fetches bib, mfhd or item record matching the given record id. Returns the response as XML.
#

use strict;
use CGI;
use DBI;
use POSIX;
use Cwd 'abs_path';
use File::Basename 'dirname';
use Unicode::Normalize qw(NFC compose);
#use Unicode::Normalize;

my $base_path = dirname(abs_path($0)) . '/';
my $config_file = $base_path . 'get_single_record.conf';

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

writelog('info', 'Starting getSingleRecord.pl');

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
if(!check_record_id() || !check_record_type()) {
  writelog('warn', 'Request not processed. Invalid or missing parameters');
  send_http_error('405');
  writelog('info', 'Exit program');
  exit (1);
}

my $response = get_record($request_parameters{'recordId'}, $request_parameters{'recordType'});

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
sub get_record($$) {
  my($record_id, $record_type) = @_;
  my $record;
  my $record_str = "";
  my $response_str;
  my $history_str;

  open_db_connection();

  if($record_type =~ m/^bib$/) {
    $record = get_bib_record($record_id);
    $record_str = convert_to_marcxml($record, 0, 0);
    my @history = get_history($record_id, 0, 0);
    $history_str .= convert_history_to_xml(\@history, 0,0);
  } elsif ($record_type =~ m/^mfhd$/) {
    $record = get_mfhd_record($record_id);
    $record_str = convert_to_marcxml($record, 1, 0);
    my @mfhd_items = get_item_records($record_id);
    $record_str .= convert_items_list_to_marcxml(\@mfhd_items);
    my @history = get_history($record_id, 1, 0);
    $history_str .= convert_history_to_xml(\@history, 1, 0);
  } elsif($record_type =~ m/^item$/) {
    my @items = get_item_record($record_id);
    if(@items > 0) {
      for my $item (@items) {
        my @statuses = get_item_statuses(@$item[0]);
        $record_str = convert_item_to_marcxml(\@$item, \@statuses);
      }
    }
  } elsif($record_type =~ m/^auth$/) {
    $record = get_auth_record($record_id);
    $record_str = convert_to_marcxml($record,0, 1);
    my @history = get_history($record_id, 0, 1);
    $history_str .= convert_history_to_xml(\@history, 0, 1);
  }

  close_db_connection();

  writelog('info', 'Starting to create XML for output');
  if(length($record_str) > 0) { 
    $response_str .= get_xml_header();
    $response_str .= $record_str;
    if(length($history_str) > 0) {
      $response_str .= get_indent(1) . "<marcextended:actions>\n";
      $response_str .= $history_str;
      $response_str .= get_indent(1) . "</marcextended:actions>\n";
    }
    $response_str .= get_xml_footer();
  }
  writelog('info', 'Creating XML done');

  return $response_str;
}
####################################
sub get_item_records($) {
  my ($mfhd_id) = @_;
  my $sql = "
    SELECT mi.item_id
    FROM $config{'db'}{'dbname'}.mfhd_item mi
    WHERE mi.mfhd_id = $mfhd_id
  ";

  writelog('info', "Fetching item ids related to mfhd record from DB. Mfhd id: $mfhd_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @items = ();
  while( my($item_id) = $sth->fetchrow_array())
  {
    push @items, $item_id;
  }
  $sth->finish();
  writelog('debug', "Found " . @items . " item(s)");
  return @items;
}
####################################
sub convert_to_marcxml($$$) {
  my ($rec, $is_holding,$is_auth) = @_;
  if(length($rec) == 0) {
    return "";
  }
  my $indent_level_1 = get_indent(2);
  my $indent_level_2 = get_indent(3);
  my $base = substr($rec, 12, 5);
  my $leader = substr($rec, 0, 24);
  my $record_type = "Bibliographic";
  my $fields = get_indent(1) . "<marc:record>\n";

  if(length($rec) == 0) {
      return $fields;
  }

  if($is_holding) {
    $record_type = "Holdings";
  } elsif($is_auth) {
    $record_type = "Authority";
  }

  $fields .= "$indent_level_1<marc:recordTypeType>$record_type</marc:recordTypeType>\n";
  $fields .= "$indent_level_1<marc:leader>" . escape_xml($leader) . "</marc:leader>\n";

  my $current_pos = 24;

  while(ord(substr($rec, $current_pos, 1)) != 0x1e && $current_pos < length($rec)) {
    my $field_code = substr($rec, $current_pos, 3);
    my $len = substr($rec, $current_pos + 3, 4);
    my $pos = substr($rec, $current_pos + 7, 5);
  
    $current_pos += 12;

    if($field_code < 10) {
      my $field = escape_xml(substr($rec, $base + $pos, $len));
      $field =~ s/\x1e$//g;
      $fields .= "$indent_level_1<marc:controlfield tag=\"$field_code\">$field</marc:controlfield>\n";
    } else {
      my $ind1 = substr($rec, $base + $pos, 1);
      my $ind2 = substr($rec, $base + $pos + 1, 1);
      my $field_contents = substr($rec, $base + $pos + 2, $len - 2);
      my $new_field = "$indent_level_1<marc:datafield tag=\"$field_code\" ind1=\"$ind1\" ind2=\"$ind2\">\n";

      my @subfields = split(/[\x1e\x1f]/, $field_contents);
      my $have_subfields = 0;
      foreach my $subfield (@subfields)
      {
        my $subfield_code = substr($subfield, 0, 1);
        next if ($subfield_code eq '');

        # Check if the subfield should be stripped
        foreach my $strip ($config{'strip_fields'})
        {
	  next subfield if ($field_code eq substr($strip, 0, 3) && index($subfield_code, substr($strip, 3) >= 0));
        }

        my $subfield_data = escape_xml(substr($subfield, 1, length($subfield)));
        if ($subfield_data ne '')
        {
	  $new_field .= "$indent_level_2<marc:subfield code=\"$subfield_code\">$subfield_data</marc:subfield>\n";
	  $have_subfields = 1;
        }
      }
      $new_field .= "$indent_level_1</marc:datafield>\n";

      if ($have_subfields) {
	$fields .= $new_field;
      }
    }
  }
  $fields .= get_indent(1) . "</marc:record>\n";
  return $fields;
}
####################################
sub convert_item_to_marcxml($$) {
  my ($item, $statuses) = @_;
  my $fields = get_indent(1) . "<marcextended:item>\n";
  my $spacing = get_indent(2);

  $fields .= "$spacing<marcextended:itemId>@{$item}[0]</marcextended:itemId>\n";
  $fields .= "$spacing<marcextended:mfhdId>@{$item}[22]</marcextended:mfhdId>\n";
  $fields .= "$spacing<marcextended:barcode>@{$item}[1]</marcextended:barcode>\n";
  $fields .= "$spacing<marcextended:permLocId>@{$item}[2]</marcextended:permLocId>\n";
  $fields .= "$spacing<marcextended:tempLocId>@{$item}[3]</marcextended:tempLocId>\n";
  $fields .= "$spacing<marcextended:itemTypeId>@{$item}[4]</marcextended:itemTypeId>\n";
  $fields .= "$spacing<marcextended:tempItemTypeId>@{$item}[5]</marcextended:tempItemTypeId>\n";
  $fields .= "$spacing<marcextended:mediaTypeId>@{$item}[6]</marcextended:mediaTypeId>\n";
  $fields .= "$spacing<marcextended:copyNumber>@{$item}[7]</marcextended:copyNumber>\n";
  $fields .= "$spacing<marcextended:pieces>@{$item}[8]</marcextended:pieces>\n";
  $fields .= "$spacing<marcextended:price>@{$item}[9]</marcextended:price>\n";
  $fields .= "$spacing<marcextended:spineLabel>@{$item}[10]</marcextended:spineLabel>\n";
  $fields .= "$spacing<marcextended:caption>@{$item}[11]</marcextended:caption>\n";
  $fields .= "$spacing<marcextended:chron>@{$item}[12]</marcextended:chron>\n";
  $fields .= "$spacing<marcextended:freeText>@{$item}[13]</marcextended:freeText>\n";
  $fields .= "$spacing<marcextended:itemEnum>@{$item}[14]</marcextended:itemEnum>\n";
  $fields .= "$spacing<marcextended:year>@{$item}[15]</marcextended:year>\n";

  #$fields .= "$spacing<createDate>@{$item[16]}</createDate>\n";
  #$fields .= "$spacing<createOperatorId>@{$item[17]}</createOperatorId>\n";
  #$fields .= "$spacing<createLocationId>@{$item[18]}</createLocationId>\n";
  #$fields .= "$spacing<modifyDate>@{$item[19]}</modifyDate>\n";
  #$fields .= "$spacing<modifyOperatorId>@{$item[20]}</modifyOperatorId>\n";
  #$fields .= "$spacing<modifyLocationId>@{$item[21]}</modifyLocationId>\n";

  if(@{$statuses} >0) {
    $fields .= "$spacing<marcextended:statuses>\n";
    for my $status (@{$statuses}) {
      $fields .= get_indent(3) . "<marcextended:status>@{$status}[0]</marcextended:status>\n";
      $fields .= get_indent(3) . "<marcextended:statusDate>@{$status}[1]</marcextended:statusDate>\n";
    }
    $fields .= "$spacing</marcextended:statuses>\n";
  } else {
    $fields .= "$spacing<marcextended:statuses />\n";
  }
  $fields .= get_indent(1) . "</marcextended:item>\n";

  return $fields;
}
####################################
sub convert_items_list_to_marcxml($) {
  my ($mfhd_items) = @_;
  my $fields;

  if(@$mfhd_items > 0) {
    $fields = get_indent(1) . "<marcextended:items>\n";
    for my $mfhd_item (@$mfhd_items) {
      $fields .= get_indent(2) . "<marcextended:item>\n";
      $fields .= get_indent(3) . "<marcextended:itemId>$mfhd_item</marcextended:itemId>\n";
      $fields .= get_indent(2) . "</marcextended:item>\n";
    }
    $fields .= get_indent(1) . "</marcextended:items>\n";
  } else {
   $fields = "";
  }
  return $fields;
}
####################################
sub convert_history_to_xml($$$) {
  my ($actions, $is_holding, $is_auth) = @_;
  my $record_type = "Bibliographic";
  my $fields;

  if($is_holding) {
    $record_type = "Holdings";
  } elsif($is_auth) {
    $record_type = "Authority";
  }

  for my $action (@$actions) {
    $fields .= get_indent(2) . "<marcextended:action>\n";
    my $spacing = get_indent(3);

    $fields .= "$spacing<marcextended:recordType>$record_type</marcextended:recordType>\n";
    $fields .= "$spacing<marcextended:recordId>@{$action}[0]</marcextended:recordId>\n";
    $fields .= "$spacing<marcextended:operatorId>@{$action}[1]</marcextended:operatorId>\n";
    $fields .= "$spacing<marcextended:actionDate>@{$action}[2]</marcextended:actionDate>\n";
    $fields .= "$spacing<marcextended:locationId>@{$action}[3]</marcextended:locationId>\n";
    $fields .= "$spacing<marcextended:encodingLevel>@{$action}[4]</marcextended:encodingLevel>\n";
    $fields .= "$spacing<marcextended:suppressInOpac>@{$action}[5]</marcextended:suppressInOpac>\n";
    $fields .= "$spacing<marcextended:actionTypeId>@{$action}[6]</marcextended:actionTypeId>\n";

    $fields .= get_indent(2) . "</marcextended:action>\n";
  }
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
  $response .= "<marcextended:recordData xmlns:marcextended=\"http://linneatest.csc.fi/marcextended\"";
  $response .= " xmlns:marc=\"http://www.loc.gov/MARC21/slim\">\n";
  return $response;
}
####################################
sub get_xml_footer() {
  return "</marcextended:recordData>\n";
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

  $dbh->do("ALTER SESSION SET NLS_DATE_FORMAT='DD.MM.YYYY HH24:mi:ss'");
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
sub get_bib_record($) {
  my ($bib_id) = @_;
  my $sql = "
    SELECT MARC_RECORD 
    FROM $config{'db'}{'dbname'}.BIBBLOB_VW
    WHERE BIB_ID = $bib_id
  ";

  writelog('info', "Fetching bib record from DB bib id: $bib_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
    or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
    or die DateTime() . "|" . $dbh->errstr;
  
  my $marc = undef;
  if ($marc = $sth->fetchrow_array())
  {
    $marc =~ s/\x1d.*/\x1d/g;
  }
  $sth->finish();

  if(length($marc) == 0) {
    writelog('debug', 'No bib record matching the given bib id was found');
  } 
  return $marc;  
}
####################################
sub get_auth_record($) {
  my ($auth_id) = @_;
  my $sql = "
    SELECT MARC_RECORD
    FROM $config{'db'}{'dbname'}.AUTHBLOB_VW
    WHERE AUTH_ID = $auth_id
  ";

  writelog('info', "Fetching auth record from DB auth id: $auth_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my $marc = undef;
  if ($marc = $sth->fetchrow_array())
  {
    $marc =~ s/\x1d.*/\x1d/g;
  }
  $sth->finish();

  if(length($marc) == 0) {
    writelog('debug', 'No auth record matching the given auth id was found');
  }
  return $marc;
}

####################################
sub get_mfhd_record($) {
  my ($mfhd_id) = @_;
  my $sql = "
    SELECT MARC_RECORD
    FROM $config{'db'}{'dbname'}.MFHDBLOB_VW
    WHERE MFHD_ID = $mfhd_id
  ";

  writelog('info', "Fetching mfhd record from DB. Mfhd id: $mfhd_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;
  
  my $marc = undef;
  if ($marc = $sth->fetchrow_array())
  {
    $marc =~ s/\x1d.*/\x1d/g;
  }
  $sth->finish();

  if(length($marc) == 0) {
    writelog('debug', 'No mfhd record matching the given mfhd id was found');
  }
  return $marc;
}
####################################
sub get_item_record($) {
    my ($item_id) = @_;
  my $sql = "
    SELECT i.item_id, ib.item_barcode, i.perm_location, i.temp_location, 
      i.item_type_id, i.temp_item_type_id, i.media_type_id, i.copy_number, 
      i.pieces, i.price, i.spine_label, mi.caption, mi.chron, mi.freetext, 
      mi.item_enum, mi.year, i.create_date, i.create_operator_id, 
      i.create_location_id, i.modify_date, i.modify_operator_id, 
      i.modify_location_id, mi.mfhd_id
    FROM $config{'db'}{'dbname'}.mfhd_item mi, item i
    LEFT OUTER JOIN item_barcode ib on i.item_id = ib.item_id
    AND ib.barcode_status = 1
    WHERE i.item_id = $item_id
    AND mi.item_id = i.item_id
  ";

  writelog('info', "Fetching item record from DB. Item id: $item_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @items = ();
  while( my(@item) = $sth->fetchrow_array())
  {
    push @items, [ @item ];
  }
  $sth->finish();
  writelog('debug', "Found " . @items . " item(s)");
  return @items;
}
####################################
sub get_item_statuses($) {
  my ($item_id) = @_;
  my $sql = "
    SELECT item_status, item_status_date
    FROM $config{'db'}{'dbname'}.item_status
    WHERE item_id = $item_id
  ";

  writelog('debug', "Fetching item statuses from DB. Item id: $item_id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @statuses = ();
  while( my(@status) = $sth->fetchrow_array())
  {
      push(@statuses, [ @status ]);
  }
  $sth->finish();
  writelog('debug', "Found " . @statuses . " status(es)");
  return @statuses;
}
####################################
sub get_history($$$) {
  my ($id, $is_holding, $is_auth) = @_;
  my $table = "bib";
  if($is_holding) {
     $table = "mfhd";
  } elsif($is_auth) {
     $table = "auth";
  }

  my $sql = "
    SELECT *
    FROM $config{'db'}{'dbname'}." . $table . "_history
    WHERE " . $table . "_id = $id
    ORDER BY action_date desc
  ";

  writelog('info', "Fetching $table history from DB. " . ucfirst($table) . " id: $id");

  # Prepare and execute query
  my $sth = $dbh->prepare($sql)
      or die DateTime() . "|" . $dbh->errstr;
  $sth->execute
      or die DateTime() . "|" . $dbh->errstr;

  my @actions = ();
  while( my(@action) = $sth->fetchrow_array())
  {
    push @actions, [ @action ];
  }
  $sth->finish();
  writelog('debug', "Found " . @actions . " action(s)");
  return @actions;
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
sub check_record_id() {
  writelog('debug', 'Checking request parameters');
  if(exists($request_parameters{'recordId'})) {
    writelog('debug', 'Record id found');
    if($request_parameters{'recordId'} =~ m/^[0-9]+$/) {
      writelog('debug', 'Record id contains only numbers');
      return 1;
    }
    writelog('info', "Bad formed record id: $request_parameters{'recordId'}");
    return 0;
  }
  writelog('info', 'No record id found');
  return 0;
}
###################################
sub check_record_type() {
  writelog('debug', 'Checking request parameters');
  if(exists($request_parameters{'recordType'})) {
	  writelog('debug', 'Record type found');
	  if($request_parameters{'recordType'} =~ m/^(bib|auth|mfhd|item)$/) {
	    writelog('debug', "Record type detected: $request_parameters{'recordType'}");
	    return 1;
	  }
	  writelog('info', "Invalid record type: $request_parameters{'recordType'}");
	  return 0;
  }
  writelog('info', 'No record type found');
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
