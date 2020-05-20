import requests
import sys
import json
import os
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import yaml
from jinja2 import Template
import secrets
import meraki
import pycurl
from io import BytesIO
from operator import itemgetter
import re
import urllib.request
from datetime import datetime, timedelta


requests.packages.urllib3.disable_warnings()

from requests.packages.urllib3.exceptions import InsecureRequestWarning

def get_logger(logfile, level):
    '''
    Create a logger
    '''
    if logfile is not None:

        '''
        Create the log directory if it doesn't exist
        '''

        fldr = os.path.dirname(logfile)
        if not os.path.exists(fldr):
            os.makedirs(fldr)

        logger = logging.getLogger()
        logger.setLevel(level)
 
        log_format = '%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(lineno)-3d | %(message)s'
        formatter = logging.Formatter(log_format)
 
        file_handler = TimedRotatingFileHandler(logfile, when='midnight', backupCount=7)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

        '''
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)
        '''

        return logger

    return None


def get_device_ids(jsessionid,token,template_id):

    if token is not None:
        headers = {'Content-Type': "application/json",'Cookie': jsessionid, 'X-XSRF-TOKEN': token}
    else:
        headers = {'Content-Type': "application/json",'Cookie': jsessionid}

    base_url = "https://%s:%s/dataservice"%(vmanage_host,vmanage_port)

    api_url = '/template/device/config/attached/' + template_id

    url = base_url + api_url

    response = requests.get(url=url, headers=headers,verify=False)

    if response.status_code == 200:
        device_ids = []
        for device in response.json()['data']:
            device_ids.append(device['uuid'])
        if logger is not None:
            logger.info("Device ids " + str(device_ids))
        return device_ids
    else:
        if logger is not None:
            logger.error("Failed to get device ids " + str(response.text))
        exit()

def get_device_inputs(jsessionid,token,template_id, device_ids):

    if token is not None:
        headers = {'Content-Type': "application/json",'Cookie': jsessionid, 'X-XSRF-TOKEN': token}
    else:
        headers = {'Content-Type': "application/json",'Cookie': jsessionid}

    payload = {
        'templateId': template_id,
        'deviceIds': device_ids,
        'isEdited': True,
        'isMasterEdited': False
    }

    base_url = "https://%s:%s/dataservice"%(vmanage_host,vmanage_port)

    api_url = '/template/device/config/input'

    url = base_url + api_url    

    response = requests.post(url=url, headers=headers, data=json.dumps(payload), verify=False)

    if response.status_code == 200:

        device_inputs = response.json()['data']

        for input in device_inputs:
            input['csv-templateId'] = template_id
    
        if logger is not None:
            logger.info("Device config input" + str(device_inputs))
    else:
        if logger is not None:
            logger.error("Failed to get device config input " + str(response.text))
        exit()

    return device_inputs


class Authentication:

    @staticmethod
    def get_jsessionid(vmanage_host, vmanage_port, username, password):
        api = "/j_security_check"
        base_url = "https://%s:%s"%(vmanage_host, vmanage_port)
        url = base_url + api
        payload = {'j_username' : username, 'j_password' : password}
        
        response = requests.post(url=url, data=payload, verify=False)
        try:
            cookies = response.headers["Set-Cookie"]
            jsessionid = cookies.split(";")
            return(jsessionid[0])
        except:
            if logger is not None:
                logger.error("No valid JSESSION ID returned\n")
            exit()
       
    @staticmethod
    def get_token(vmanage_host, vmanage_port, jsessionid):
        headers = {'Cookie': jsessionid}
        base_url = "https://%s:%s"%(vmanage_host, vmanage_port)
        api = "/dataservice/client/token"
        url = base_url + api      
        response = requests.get(url=url, headers=headers, verify=False)
        if response.status_code == 200:
            return(response.text)
        else:
            return None

class create_ipsec_tunnel:

    def __init__(self, vmanage_host, vmanage_port, jsessionid, token):
        base_url = "https://%s:%s/dataservice/"%(vmanage_host, vmanage_port)
        self.base_url = base_url
        self.jsessionid = jsessionid
        self.token = token

    def get_interface_ip(self,system_ip,vpn0_source_interface):
        if self.token is not None:
            headers = {'Cookie': self.jsessionid, 'X-XSRF-TOKEN': self.token}
        else:
            headers = {'Cookie': self.jsessionid}

        api = "device/interface?deviceId=%s&vpn-id=0&ifname=%s&af-type=ipv4"%(system_ip,vpn0_source_interface)
        url = self.base_url + api

        response = requests.get(url=url,headers=headers,verify=False)
        if response.status_code == 200:
            try:
                data = response.json()["data"][0]
                ip_address = data["ip-address"].split("/")[0]
                if logger is not None:
                    logger.info("\nsource ip address for tunnels is " + str(ip_address))
                return ip_address
            except Exception as e:
                if logger is not None:
                    logger.error("\nError fetching ip address " + str(e))
                print("\nError fetching ip address",e)
                exit()
    
    def get_device_templateid(self,device_template_name):
        if self.token is not None:
            headers = {'Cookie': self.jsessionid, 'X-XSRF-TOKEN': self.token}
        else:
            headers = {'Cookie': self.jsessionid}
        api = "template/device"
        url = self.base_url + api        
        template_id_response = requests.get(url=url, headers=headers, verify=False)
        device_info = dict()

        if template_id_response.status_code == 200:
            items = template_id_response.json()['data']
            template_found=0
            if logger is not None:
                logger.info("\nFetching Template uuid of %s"%device_template_name)
            print("\nFetching Template uuid of %s"%device_template_name)
            for item in items:
                if item['templateName'] == device_template_name:
                    device_info["device_template_id"] = item['templateId']
                    device_info["device_type"] = item["deviceType"]
                    template_found=1
                    return(device_info)
            if template_found==0:
                if logger is not None:
                    logger.error("\nDevice Template is not found")
                print("\nDevice Template is not found")
                exit()
        else:
            if logger is not None:
                logger.error("\nDevice Template is not found " + str(template_id_response.text))
            print("\nError fetching list of templates")
            exit()


    def get_feature_templates(self,device_template_id):
        if self.token is not None:
            headers = {'Cookie': self.jsessionid, 'X-XSRF-TOKEN': self.token}
        else:
            headers = {'Cookie': self.jsessionid}        

        #Fetching feature templates associated with Device template.
             
        api = "template/device/object/%s"%(device_template_id)
        url = self.base_url + api     
        template_response = requests.get(url=url, headers=headers, verify=False)

        if logger is not None:
            logger.info("\nFetching feature templates")
        print("\nFetching feature templates")

        if template_response.status_code == 200:
            feature_template_ids=template_response.json()
            return(feature_template_ids)
        else:
            print("\nError fetching feature template ids")
            exit()

    def create_ipsec_templates(self,device_info):
            if self.token is not None:
                headers = {'Content-Type': "application/json",'Cookie': self.jsessionid, 'X-XSRF-TOKEN': self.token}
            else:
                headers = {'Content-Type': "application/json",'Cookie': self.jsessionid}

            with open("ipsec-tunnel-json.j2") as f:
                ipsec_int = Template(f.read())

            print("\nCreating IPsec features templates")
            if logger is not None:
                logger.info("\nCreating IPsec features templates")

            
            tunnel_data = dict()
            tunnel_data["template_name"] = "viptela_mx_ipsec_primary"
            tunnel_data["device_type"] = device_info["device_type"]
            tunnel_data["viptela_mx_ipsec_if_name"] = "viptela_mx_ipsec_interface_1"
            tunnel_data["viptela_mx_ipsec_if_ipv4_address"] = "viptela_mx_ipsec_ipv4_add_1"
            tunnel_data["viptela_mx_ipsec_if_tunnel_source_ip"]   = "viptela_mx_ipsec_src_1"
            tunnel_data["viptela_mx_ipsec_if_tunnel_destination"] = "viptela_mx_ipsec_dst_1"
            tunnel_data["viptela_mx_ipsec_if_pre_shared_secret"] = "viptela_mx_ipsec_psk_1"
            tunnel_data["ike_cipher_suite"] = 'ike_cipher_suite'
            tunnel_data["ike_dh_group"] = 'ike_dh_group'
            tunnel_data["ipsec_cipher_suite"] = 'ipsec_cipher_suite'
            tunnel_data["ipsec_pfs"] = 'ipsec_pfs'

            pri_ipsec_int_payload = ipsec_int.render(config=tunnel_data)

            if logger is not None:
                logger.info("\nPrimary Interface Template payload " + str(pri_ipsec_int_payload))

            api = "template/feature/"
            url = self.base_url + api        
            pri_template_response = requests.post(url=url, data=pri_ipsec_int_payload,headers=headers, verify=False)

            if logger is not None:
                logger.info("\nPrimary Interface Template status code " + str(pri_template_response.status_code))

            if pri_template_response.status_code == 200:
                if logger is not None:
                    logger.info("\nCreated primary ipsec interface template ID: " + str(pri_template_response.json()))
                pri_ipsec_int_template_id = pri_template_response.json()['templateId']
            else:
                if logger is not None:
                    logger.error("\nFailed creating primary ipsec interface template, error: " + str(pri_template_response.text))
                print("\nFailed creating primary ipsec interface template, error: ",pri_template_response.text)
                exit()
            
            pri_ipsec_int_template = {
                                       "templateId": pri_ipsec_int_template_id,
                                       "templateType": "vpn-vedge-interface-ipsec",
                                     }


            ipsec_int_template = [pri_ipsec_int_template]
            
            return(ipsec_int_template)
            
    def push_device_template(self,device_info,ipsec_templateid,ipsec_parameters,feature_template_ids):
        
        if self.token is not None:
            headers = {'Content-Type': "application/json",'Cookie': self.jsessionid, 'X-XSRF-TOKEN': self.token}
        else:
            headers = {'Content-Type': "application/json",'Cookie': self.jsessionid}
        device_template_id = device_info["device_template_id"]
        api = "template/device/%s"%device_template_id
        url = self.base_url + api

        feature_template_list = feature_template_ids["generalTemplates"]

        '''for item in feature_template_list:
            if item["templateType"] == "vpn-vedge":
                sub_templates = item["subTemplates"]
                sub_templates.append(ipsec_templateid[0])
                break'''

        service_vpn_templates = list()
            
        for index,item in enumerate(feature_template_list):
            if item["templateType"] == "vpn-vedge":
                sub_templates = item["subTemplates"]
                sub_templates.append(ipsec_templateid[0])
                #sub_templates.append(ipsec_templateid[1])
                temp = index+2
                while(1):
                    if feature_template_list[temp]['templateType'] == 'vpn-vedge':
                        service_vpn_templates.append(feature_template_list[temp]['templateId'])
                    temp = temp+1
                    if len(feature_template_list) < temp+1:
                        break
                break
            
        payload = {
                    "templateId":device_template_id,"templateName":device_template_name,
                    "templateDescription":feature_template_ids["templateDescription"],
                    "deviceType":feature_template_ids["deviceType"],
                    "configType":"template","factoryDefault":False,
                    "policyId":feature_template_ids["policyId"],
                    "featureTemplateUidRange":[],"connectionPreferenceRequired":True,
                    "connectionPreference":True,"policyRequired":True,
                    "generalTemplates":feature_template_ids["generalTemplates"],
                  }
        payload = json.dumps(payload)

        if logger is not None:
            logger.info("\nDevice template JSON payload " + str(payload))
        device_template_edit_res = requests.put(url=url,data=payload,headers=headers,verify=False)

        if device_template_edit_res.status_code == 200:
            items = device_template_edit_res.json()['data']['attachedDevices']
            device_uuid = list()
            for i in range(len(items)):
                device_uuid.append(items[i]['uuid'])
        else:
            print("\nError editing device template\n")
            print(device_template_edit_res.text)
            exit()

        if logger is not None:
            logger.info("\nDevice uuid: %s"%device_uuid)
        print("\nDevice uuid: %s"%device_uuid)

        # Fetching Device csv values
        if logger is not None:
            logger.info("\nFetching device csv values")
        print("\nFetching device csv values")

        payload = { 
                    "templateId":device_template_id,
                    "deviceIds":device_uuid,
                    "isEdited":True,
                    "isMasterEdited":True
                  }
        payload = json.dumps(payload)
        
        api = "template/device/config/input/"
        url = self.base_url + api
        device_csv_res = requests.post(url=url, data=payload,headers=headers, verify=False)

        if device_csv_res.status_code == 200:
            device_csv_values = device_csv_res.json()['data']
        else:
            if logger is not None:
                logger.error("\nError getting device csv values" + str(device_csv_res.text))
            print("\nError getting device csv values")
            exit()

        # Adding the values to device specific variables

        temp = device_csv_values

        for item1 in temp:
            sys_ip = item1["csv-deviceIP"]
            for item2 in ipsec_parameters:
                if sys_ip == item2["device_sys_ip"]:
                    temp_pri_ipsec_id = item2["pri_ipsec_id"] # to use ipsec interface id in service vpn template  update
                    item1["/0/viptela_mx_ipsec_interface_1/interface/if-name"] = item2["pri_ipsec_id"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/ip/address"] = item2["pri_ipsec_ip"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/tunnel-source"] = item2["viptela_mx_primary_src_ip"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/tunnel-destination"] = item2["viptela_mx_primary_dst_ip"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/ike/authentication-type/pre-shared-key/pre-shared-secret"] = item2["pre_shared_key"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/ike/ike-ciphersuite"] = item2["ike_cipher_suite"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/ike/ike-group"] = item2["ike_dh_group"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/ipsec/ipsec-ciphersuite"] = item2["ipsec_cipher_suite"]
                    item1["/0/viptela_mx_ipsec_interface_1/interface/ipsec/perfect-forward-secrecy"] = item2["ipsec_pfs"]
                    break
                else:
                    continue

        if logger is not None:
            logger.info("\nUpdated device csv values are" + str(temp))
        device_csv_values = temp

        # Attaching new Device template

        print("\nAttaching new device template")
        if logger is not None:
            logger.info("\nAttaching new device template")

        payload = { 
                    "deviceTemplateList":[
                    {
                        "templateId":device_template_id,
                        "device":device_csv_values,
                        "isEdited":True,
                        "isMasterEdited":False
                    }]
                  }
        payload = json.dumps(payload)

        api = "template/device/config/attachfeature"
        url = self.base_url + api
        attach_template_res = requests.post(url=url, data=payload,headers=headers, verify=False)


        if attach_template_res.status_code == 200:
            attach_template_pushid = attach_template_res.json()['id']
        else:
            if logger is not None:
                logger.error("\nAttaching device template failed, "+str(attach_template_res.text))
            print("\nAttaching device template failed")
            exit()

        # Fetch the status of template push

        api = "device/action/status/%s"%attach_template_pushid
        url = self.base_url + api        

        while(1):
            template_status_res = requests.get(url,headers=headers,verify=False)
            if template_status_res.status_code == 200:
                template_push_status = template_status_res.json()
                if template_push_status['summary']['status'] == "done":
                    if 'Success' in template_push_status['summary']['count']:
                        print("\nUpdated IPsec templates successfully")
                        if logger is not None:
                            logger.info("\nUpdated IPsec templates successfully")
                    elif 'Failure' in template_push_status['summary']['count']:
                        print("\nFailed to update IPsec templates")
                        if logger is not None:
                            logger.info("\nFailed to update IPsec templates " + str(template_push_status["data"][0]["activity"]))
                        exit()
                    break
            else:
                if logger is not None:
                    logger.error("\nFetching template push status failed " + str(template_status_res.text))                
                print("\nFetching template push status failed")
                exit()

        # Update service VPN template with IPsec route

        print("\nService VPN Templates list", service_vpn_templates)

        for item in service_vpn_templates:
            
            api = "template/feature/object/%s"%item
            url = self.base_url + api

            service_vpn_def = requests.get(url,headers=headers,verify=False)

            if service_vpn_def.status_code == 200:
                template_def = service_vpn_def.json()

                ipsec_route_def = template_def["templateDefinition"]["ip"]["ipsec-route"]

                if not ipsec_route_def:
                    ipsec_route_def["vipType"] = "constant"
                    ipsec_route_def["vipValue"] = [
                                                    {
                                                        "prefix": {
                                                        "vipObjectType": "object",
                                                        "vipType": "constant",
                                                        "vipValue": device_info["service_vpn_ipsec_route"],
                                                        "vipVariableName": "vpn_ipsec_route_ipsec_route_prefix"
                                                        },
                                                        "vpn": {
                                                        "vipObjectType": "object",
                                                        "vipType": "constant",
                                                        "vipValue": 0
                                                        },
                                                        "interface": {
                                                        "vipObjectType": "list",
                                                        "vipType": "constant",
                                                        "vipValue": [
                                                            temp_pri_ipsec_id
                                                        ],
                                                        "vipVariableName": "vpn_ipsec_route_ipsec_route_interface"
                                                        },
                                                        "priority-order": [
                                                        "prefix",
                                                        "vpn",
                                                        "interface"
                                                        ]
                                                    }
                                                  ]

                    ipsec_route_def["vipObjectType"] = "tree"
                    ipsec_route_def["vipPrimaryKey"] = [
                                                         "prefix"
                                                       ]
                
                else:
                    temp  =            {
                                            "prefix": {
                                            "vipObjectType": "object",
                                            "vipType": "constant",
                                            "vipValue": device_info["service_vpn_ipsec_route"],
                                            "vipVariableName": "vpn_ipsec_route_ipsec_route_prefix"
                                            },
                                            "vpn": {
                                            "vipObjectType": "object",
                                            "vipType": "constant",
                                            "vipValue": 0
                                            },
                                            "interface": {
                                            "vipObjectType": "list",
                                            "vipType": "constant",
                                            "vipValue": [
                                                temp_pri_ipsec_id
                                            ],
                                            "vipVariableName": "vpn_ipsec_route_ipsec_route_interface"
                                            },
                                            "priority-order": [
                                            "prefix",
                                            "vpn",
                                            "interface"
                                            ]
                                        }
                    
                    ipsec_route_def["vipValue"].append(temp)


                template_def["templateDefinition"]["ip"]["ipsec-route"] = ipsec_route_def

            api = "template/feature/%s"%item
            url = self.base_url + api

            payload = {
                         "templateName" : template_def["templateName"],
                         "templateDescription" : template_def["templateDescription"],
                         "templateType" : template_def["templateType"],
                         "deviceType" : template_def["deviceType"],
                         "templateMinVersion" : template_def["templateMinVersion"],
                         "templateDefinition" : template_def["templateDefinition"],
                         "factoryDefault" : False
                      }

            payload = json.dumps(payload)

            if logger is not None:
                logger.info("\nService VPN template JSON payload " + str(payload))

            update_service_vpn = requests.put(url,headers=headers,data=payload,verify=False)

            if update_service_vpn.status_code == 200:
                master_templates_affected = update_service_vpn.json()["masterTemplatesAffected"]
            else:
                if logger is not None:
                    logger.error("\nFailed to edit Service VPN template " + str(update_service_vpn.text))
                exit()

            # Get device uuid and csv variables for each template id which is affected by prefix list edit operation

            inputs = []

            for template_id in master_templates_affected:
                device_ids = get_device_ids(self.jsessionid,self.token,template_id)
                device_inputs = get_device_inputs(self.jsessionid,self.token,template_id,device_ids)
                inputs.append((template_id, device_inputs))


            device_template_list = []
            
            for (template_id, device_input) in inputs:
                device_template_list.append({
                    'templateId': template_id,
                    'isEdited': True,
                    'device': device_input
                })


            #api_url for CLI template 'template/device/config/attachcli'

            api_url = 'template/device/config/attachfeature'

            url = self.base_url + api_url

            payload = { 'deviceTemplateList': device_template_list }

            response = requests.post(url=url, headers=headers,  data=json.dumps(payload), verify=False)

            if response.status_code == 200:
                process_id = response.json()["id"]
                if logger is not None:
                    logger.info("Attach template process id " + str(response.text))
            else:
                if logger is not None:
                    logger.error("Template attach process failed " + str(response.text)) 
                exit()    

            api_url = 'device/action/status/' + process_id  

            url = self.base_url + api_url

            while(1):
                time.sleep(10)
                response = requests.get(url=url, headers=headers, verify=False)
                if response.status_code == 200:
                    if response.json()['summary']['status'] == "done":
                        logger.info("\nUpdated Service VPN template %s successfully"%item)
                        print("\nUpdated Service VPN template %s successfully"%item)
                        break
                    else:
                        continue
                else:
                    logger.error("\nFetching template push status failed " + str(response.text))
                    exit()


if __name__ == "__main__":
    try:
        log_level = logging.DEBUG
        logger = get_logger("log/viptela_mx_logs.txt", log_level)
        if logger is not None:
            logger.info("Loading configuration details from YAML\n")
            print("Loading configuration details from YAML\n")
        with open("config_details.yaml") as f:
            config = yaml.safe_load(f.read())
        
        vmanage_host = config["vmanage_host"]
        vmanage_port = config["vmanage_port"]
        vmanage_username = config["vmanage_username"]
        vmanage_password = config["vmanage_password"]
        device_template_name = config["device_template_name"]
        api_key = config["api_key"]
        orgName = config["orgName"]
        service_vpn_ipsec_route = config.get("service_vpn_ipsec_route","0.0.0.0/0")


        '''
        Below is a list of all the necessary Meraki credentials
        '''

        # Meraki credentials are placed below
        meraki_config = {
            'api_key': api_key,
            'orgName': orgName
        }

        # writing function to obtain org ID via linking ORG name
        mdashboard = meraki.DashboardAPI(meraki_config['api_key'])
        result_org_id = mdashboard.organizations.getOrganizations()
        for x in result_org_id:
            if x['name'] == meraki_config['orgName']:
                meraki_config['org_id'] = x['id']

        # branch subnets is a variable to display local branch site info
        branchsubnets = []
        # variable with new and existing s2s VPN config
        merakivpns = []

        # performing initial get to obtain all Meraki existing VPN info to add to merakivpns list above
        originalvpn = mdashboard.organizations.getOrganizationThirdPartyVPNPeers(
            meraki_config['org_id']
        )
        merakivpns.append(originalvpn)


        
        Auth = Authentication()
        jsessionid = Auth.get_jsessionid(vmanage_host,vmanage_port,vmanage_username,vmanage_password)
        token = Auth.get_token(vmanage_host,vmanage_port,jsessionid)
        ipsec_tunnel = create_ipsec_tunnel(vmanage_host,vmanage_port,jsessionid, token)

        ipsec_parameters = list()

        # Meraki call to obtain Network information
        tagsnetwork = mdashboard.networks.getOrganizationNetworks(meraki_config['org_id'])

        # loop that iterates through the variable tagsnetwork and matches networks with vWAN in the tag
        for i in tagsnetwork:
            if i['tags'] is None or i['name'] == 'Tag-Placeholder':
                pass
            elif "viptela-" in i['tags']:
                network_info = i['id'] # need network ID in order to obtain device/serial information
                netname = i['name'] # network name used to label Meraki VPN and Azure config
                nettag = i['tags']  # obtaining all tags for network as this might be used for failover
                va = mdashboard.networks.getNetworkSiteToSiteVpn(network_info) # gets branch local vpn subnets
                testextract = ([x['localSubnet'] for x in va['subnets']
                                if x['useVpn'] == True])  # list comprehension to filter for subnets in vpn
                (testextract)
                privsub = str(testextract)[1:-1] # needed to parse brackets
                devices = mdashboard.devices.getNetworkDevices(network_info)
                x = devices[0]
                up = x['serial'] # serial number to later obtain the uplink information for the appliance
                firmwareversion = x['firmware'] # now we obtained the firmware version, need to still add the validation portion
                firmwarecompliance = str(firmwareversion).startswith("wired-15") # validation to say True False if appliance is on 15 firmware
                if firmwarecompliance == True:
                    print("firmware is compliant, continuing")
                else:
                    break # if box isnt firmware compliant we break from the loop
                modelnumber = x['model']

                uplinks = mdashboard.devices.getNetworkDeviceUplink(network_info, up) # obtains uplink information for branch

                # creating keys for dictionaries inside dictionaries
                uplinks_info = dict.fromkeys(['WAN1', 'WAN2', 'Cellular'])
                uplinks_info['WAN1'] = dict.fromkeys(
                    ['interface', 'status', 'ip', 'gateway', 'publicIp', 'dns', 'usingStaticIp'])
                uplinks_info['WAN2'] = dict.fromkeys(
                    ['interface', 'status', 'ip', 'gateway', 'publicIp', 'dns', 'usingStaticIp'])
                uplinks_info['Cellular'] = dict.fromkeys(
                    ['interface', 'status', 'ip', 'provider', 'publicIp', 'model', 'connectionType'])

                for uplink in uplinks:
                    if uplink['interface'] == 'WAN 1':
                        for key in uplink.keys():
                            uplinks_info['WAN1'][key] = uplink[key]
                    elif uplink['interface'] == 'WAN 2':
                        for key in uplink.keys():
                            uplinks_info['WAN2'][key] = uplink[key]
                    elif uplink['interface'] == 'Cellular':
                        for key in uplink.keys():
                            uplinks_info['Cellular'][key] = uplink[key]

                uplinksetting = mdashboard.uplink_settings.getNetworkUplinkSettings(network_info) # obtains meraki sd wan traffic shaping uplink settings
                for g in uplinks_info:
                    # loops through the variable uplinks_info which reveals the value for each uplink key
                    if uplinks_info['WAN2']['status'] == "Active" or uplinks_info['WAN2']['status'] == "Ready" and uplinks_info['WAN1']['status'] == "Active" or uplinks_info['WAN1']['status'] == "Ready":
                        print("both uplinks active")

                        pubs = uplinks_info['WAN2']['publicIp']
                        pubssec = uplinks_info['WAN1']['publicIp']
                        secondaryuplinkindicator = 'True'

                        port = (uplinksetting['bandwidthLimits']['wan1']['limitDown'])/1000
                        wan2port = (uplinksetting['bandwidthLimits']['wan2']['limitDown'])/1000

                    elif uplinks_info['WAN2']['status'] == "Active":
                        pubs = uplinks_info['WAN2']['publicIp']
                        port = (uplinksetting['bandwidthLimits']['wan2']['limitDown'])/1000

                    elif uplinks_info['WAN1']['status'] == "Active":
                        pubs = uplinks_info['WAN1']['publicIp']
                        port = (uplinksetting['bandwidthLimits']['wan1']['limitDown'])/1000

                    else:
                        print("uplink info error")

                # Don't use the same public IP for both links; use a place holder
                if(pubs == pubssec):
                        pubssec = "1.2.3.4"

                # listing site below in output with branch information
                if secondaryuplinkindicator == 'True':
                    branches = str(netname) + "  " + str(pubs) + "  " + str(port) + "  " + str(pubssec) + "  " + str(wan2port) + "  " + str(privsub)
                else:
                    branches = str(netname) + "  " +  str(pubs) + "  " +  str(port) + "  " +  str(privsub)

                print(branches)
        
        pubs = "172.31.43.179"

        # Loop over edge routers to create and deploy ipsec tunnel to viptela_mx vpn endpoint
        for device in config["vip_devices"]:
            print("Device: {}".format(device["system_ip"]))

            pri_ipsec_id = device.get("pri_ipsec_id","ipsec254")
            pri_ipsec_ip = device.get("pri_ipsec_ip","10.10.10.1/30")

            source_ip = ipsec_tunnel.get_interface_ip(device["system_ip"],device["vpn0_source_interface"])

            psk = secrets.token_hex(16)

            vedge_lan_prefix = device["vedge_lan_prefix"]

            temp_parameters =  { 
                                 "device_sys_ip":device["system_ip"],
                                 "pri_ipsec_id": pri_ipsec_id,
                                 "pri_ipsec_ip": pri_ipsec_ip,
                                 "viptela_mx_primary_src_ip": source_ip,
                                 #"viptela_mx_primary_dst_ip": device['mx_dst_ip'],
                                 "viptela_mx_primary_dst_ip": pubs,
                                 "pre_shared_key": psk,
                                 "ike_cipher_suite":device['ike_cipher_suite'],
                                 "ike_dh_group":device['ike_dh_group'],
                                 "ipsec_cipher_suite":device['ipsec_cipher_suite'],
                                 "ipsec_pfs":device['ipsec_pfs']
                               }

            ipsec_parameters.append(temp_parameters)

            if logger is not None:
                logger.info("\nTunnel parameters are " + str(ipsec_parameters))

        device_info = ipsec_tunnel.get_device_templateid(device_template_name)

        device_info["device_template_name"] = device_template_name
        device_info["service_vpn_ipsec_route"] = service_vpn_ipsec_route

        feature_templateids = ipsec_tunnel.get_feature_templates(device_info["device_template_id"])

        ipsec_templateid = ipsec_tunnel.create_ipsec_templates(device_info)
            
        ipsec_tunnel.push_device_template(device_info,ipsec_templateid,ipsec_parameters,feature_templateids)

                
        # sample IPsec template config that is later replaced with corresponding Viptela site variables (PSK pub IP, lan IP etc)
        specifictag = re.findall(r'[v]+[i]+[p]+[t]+[e]+[l]+[a]+[-]+[0-999]', str(nettag))
        print(specifictag)
        putdata1 = '{"name":"placeholder","publicIp":"192.0.0.0","privateSubnets":["0.0.0.0/0"],"secret":"meraki123", "ipsecPolicies":{"ikeCipherAlgo":["aes256"],"ikeAuthAlgo":["sha1"],"ikeDiffieHellmanGroup":["group2"],"ikeLifetime":28800,"childCipherAlgo":["aes256"],"childAuthAlgo":["sha1"],"childPfsGroup":["group2"],"childLifetime":3600},"networkTags":["west"]}'
        database = putdata1.replace("west", specifictag[0]) # applies specific tag from org overview page to ipsec config
        updatedata = database.replace('192.0.0.0', ipsec_parameters[0]["viptela_mx_primary_src_ip"])   # change variable to intance 0 IP
        updatedata1 = updatedata.replace('placeholder' , netname) # replaces placeholder value with dashboard network name
        addprivsub = updatedata1.replace('0.0.0.0/0', str(vedge_lan_prefix)) # replace with azure private networks
        addpsk = addprivsub.replace('meraki123', ipsec_parameters[0]["pre_shared_key"]) # replace with pre shared key variable generated above
        newmerakivpns = merakivpns[0]
        
        found = 0
        for site in merakivpns: # should be new meraki vpns variable
            print(type(site))
            for namesite in site:
                if netname == namesite['name']:
                    found = 1
        if found == 0:
            print(type(addpsk))
            newmerakivpns.append(json.loads(addpsk)) # appending new vpn config with original vpn config
        print(newmerakivpns)
        
        # updating preshared key for primary VPN tunnel

        for vpnpeers in newmerakivpns: # iterates through the list of VPNs from the original call
            if vpnpeers['name'] == netname: # matches against network name that is meraki network name variable
                if vpnpeers['secret'] != ipsec_parameters[0]["pre_shared_key"]: # if statement for if password in VPN doesnt match psk variable
                    vpnpeers['secret'] = ipsec_parameters[0]["pre_shared_key"] # updates the pre shared key for the vpn dictionary



        # Final Call to Update Meraki VPN config 
        updatemvpn = mdashboard.organizations.updateOrganizationThirdPartyVPNPeers(meraki_config['org_id'], newmerakivpns)
        print(updatemvpn)

    except Exception as e:
        print('Exception line number: {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)


