# vi: ts=4 expandtab
#
#    Copyright (C) 2012 CERN
#
#    Author: Tomas Karasek <tomas.karasek@cern.ch>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import subprocess
import json
import base64
import urllib2
import urllib
import cloudinit.CloudConfig as cc

def getFacterFact(factname):
    facter_process = subprocess.Popen(["facter", factname], 
                                     stdout = subprocess.PIPE,
                                     stderr = subprocess.PIPE)
    stdout, stderr = facter_process.communicate()
    output = stdout.strip()
    if not output:
        raise Exception("facter did not return anything for %s" % factname)
    return output


class ForemanAdapter:
    mandatory_fields = ['server', 'hostgroup', 'login', 'password']

    def __init__(self, log, user_data):
        self.log = log
        fq_os = (getFacterFact("operatingsystem") + " " + 
                 getFacterFact("operatingsystemrelease"))

        self.defaults = {
            "architecture": getFacterFact("architecture"),
            "model" : "Virtual Machine",
            "operatingsystem": fq_os,
            "environment": "production",
            "domain": getFacterFact("domain"),
            "ptable": "RedHat default",
        }

        self.user_data = user_data
        for field in self.mandatory_fields:
            if field not in self.user_data:
                raise Exception(("%s must be supplied in [puppet] "
                                 " section in userdata." % field))
        self.login = self.user_data.pop("login")
        self.password = self.user_data.pop("password")

    def registerToForeman(self):
        host_dict = {}
        host_dict['hostgroup_id'] = self.getMetafieldID(
            "hostgroup", self.user_data['hostgroup'])

        for field in self.defaults.keys():
            value = self.user_data.get(field, self.defaults[field])
            host_dict[field + "_id"] = self.getMetafieldID(field, value) 

        host_dict['name'] = getFacterFact("fqdn")
        host_dict['ip'] = getFacterFact("ipaddress")
        host_dict['mac'] = getFacterFact("macaddress").lower()

        self.checkForDuplicates(host_dict)

        newhost_dict = self.foremanRequest(resource = "hosts",
                                           request_type = "POST",
                                           data = {"host": host_dict})
        return newhost_dict["host"]["id"]

    def foremanRequest(self, resource, request_type, data=None):
        unsupported_types = ["DELETE"]
        if request_type == 'POST':
            data = json.dumps(data)

        url_suffix = ""
        if request_type == "GET" and data is not None:
            url_suffix = "?" + urllib.urlencode(data)
        url = self.user_data['server'] + "/" +  resource + url_suffix

        if request_type != "POST":
            data = None

        #print  "[%s]%s" % (request_type, url)

        auth = base64.encodestring("%s:%s" % (self.login, self.password))
        auth = auth.strip()

        headers = {"Content-Type": "application/json",
                   "Accept": "application/json",
                   "Authorization": "Basic %s" % auth}
        req = urllib2.Request(url=url, data=data, headers=headers)

        if request_type in unsupported_types:
           req.get_method = lambda: request_type

        out = urllib2.urlopen(req)
        return json.loads(out.read())

    def hostExists(self, hostname):
        try:
            self.foremanRequest(resource="hosts/" + hostname,
                request_type="GET")
        except urllib2.HTTPError:
            return False
        self.log.warn("host %s already exists" % hostname)
        return True

    def checkForDuplicates(self, host_dict):
        hostname = host_dict["name"]
        if not hostname.strip():
            raise Exception("Invalid hostname to check")
        # if given hostname already exists, delete the old record
        # maybe update would be better?
        if self.hostExists(hostname):
            self.log.warn("deleting %s from foreman" % hostname)
            d = self.foremanRequest(resource="hosts/" + hostname,
                request_type="DELETE")
            
        for field in ['ip', 'mac']:
            matching_hosts = self.foremanRequest(
                resource = "hosts",
                request_type="GET",
                data = {"search": "%s=%s" % (field, host_dict[field])}
            )
            if matching_hosts:
                msg = ("Host with %s %s already exists: %s" %
                      (field, host_dict[field], matching_hosts))
                raise Exception(msg)

    def getMetafieldID(self, fieldname, fieldvalue):
        get_data = {"search": fieldvalue}

        # operatinsystems can't be searched on foreman-side for some reason so
        # we need to list all entries and pick the matching one
        if fieldname in ["operatingsystem", "hostgroup"]:
            get_data = {"search": ""}

        lookup_key = 'name'
        # with hostgroups with have to use "label" instead of "name"
        if fieldname in ["hostgroup"]:
            lookup_key = 'label'
            get_data = {"search": ""}
            
        #get_data = {"name": fieldvalue}

        field_dict = self.foremanRequest(
            resource=fieldname + "s",
            request_type="GET",
            data=get_data)
        for item in field_dict:
            if item[fieldname][lookup_key] == fieldvalue:
                return int(item[fieldname]['id'])
        return None

def handle(_name, cfg, cloud, log, _args):
    if 'foreman' not in cfg:
        return
    cc.install_packages(("facter",))
    
    foreman_cfg = cfg['foreman']
    adapter = ForemanAdapter(log, foreman_cfg)
    newhost_id = adapter.registerToForeman()
