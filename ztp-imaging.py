import pyeapi
import urllib3
import requests
import json
import sys
import os

urllib3.disable_warnings()

NAUTOBOT_BASE_URL = "http://fmsddc-nbd01.amr.corp.intel.com:8080"
NAUTOBOT_GRAPHQL_URL = f"{NAUTOBOT_BASE_URL}/api/graphql/"
TOKEN = "0123456789abcdef0123456789abcdef01234567"
GRAPHQL_QUERY = json.dumps({
  "query": "query {validated_softwares {device_types {part_number } software {version software_images {image_file_name download_url image_file_checksum hashing_algorithm } } } }"
})
HEADERS = {
  'Authorization': f'Token {TOKEN}',
  'Content-Type': 'application/json'
}

# Connect to switch
switch = pyeapi.connect("socket")
node = pyeapi.client.Node(switch)

# Get switch model and EOS version
show_ver = switch.execute(["show version"]).get("result")[0]

switch_model = show_ver.get("modelName")
switch_version = show_ver.get("version")
switch_arch = show_ver.get("architecture")

# Prepare to connect to Nautobot - Test API
nautobot_test = requests.get(
    NAUTOBOT_BASE_URL,
    headers=HEADERS,
    verify=False,
)

if not nautobot_test:
    sys.exit(f"Received {nautobot_test} from {NAUTOBOT_BASE_URL}")

# Connect to Nautobot and get software version info
api_response = requests.post(NAUTOBOT_GRAPHQL_URL, headers=HEADERS, data=GRAPHQL_QUERY)
api_result = api_response.json()

nautobot_models = api_result['data']['validated_softwares']


for entry in nautobot_models:

    # entry is a dictionary of device_types
    for images in entry['software']['software_images']:
        image_url = images['download_url']
        image_checksum = images['image_file_checksum']
        image_checksum_hash = images['hashing_algorithm']

        for parts in entry['device_types']:
            part = parts['part_number']
            if switch_model == part:
                image_source = image_url
                image_file = image_url.split('/')[-1]
                image_chksum = image_checksum
                image_chksum_algorithm = image_checksum_hash

print("switch_version is", switch_version)
print("NB version is", image_file.rstrip('.swi').split('-')[-1])

# Now that we have all the data, let's make decisions
#
# Check if current version matches validated version

# Need to check architecture here, too
if switch_version != image_file.rstrip('.swi').split('-')[-1]:

    download_cmd = 'sudo curl ' + image_source + ' --max-time 600 --output /mnt/flash/' + image_file + ' --insecure'
    verify_cmd = 'verify /' + image_chksum_algorithm + ' flash:' + image_file
    bootvar_cmd = 'install source flash:' + image_file + ' now'

    # could do the download from api, but then would have to give it a bash command in order to get a long timeout,
    # so why not just go write to bash since we're here already
    os.system(download_cmd)

    # Validate checksum of download
    verify_output = switch.execute(["enable", verify_cmd]).get("result")

    for element in verify_output:
        if 'messages' in element:
           flash_chksum = element['messages'][0].split('=')[1].strip()
           #print("flash chksum is", flash_chksum, " and image chksum is", image_chksum)

    if not flash_chksum == image_chksum:
        sys.exit(f"Image download corrupt - checksum did not match.  Was {flash_chksum} locally, and nautobot says it should be {image_chksum}")

    
    switch.execute(["enable", bootvar_cmd])
    verify_boot = switch.execute(["enable", "show boot"]).get("result")[1]
    new_boot = verify_boot['softwareImage'].split(':/')[-1]

    if new_boot == image_file:
    
        #We've checked image file is good, and boot vars match, so away we go...
        #but specifically not saving any config, as we want to return in ZTP mode
        switch.execute(["enable", "reload now"])
  
    else:
        sys.exit(f"Boot var {new_boot} didn't match new image {image_file}")
