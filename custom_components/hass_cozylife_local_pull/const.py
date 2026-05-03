DOMAIN = "hass_cozylife_local_pull"

# http://doc.doit/project-5/doc-8/
SWITCH_TYPE_CODE = '00'
LIGHT_TYPE_CODE = '01'
SUPPORT_DEVICE_CATEGORY = [SWITCH_TYPE_CODE, LIGHT_TYPE_CODE]

# http://doc.doit/project-5/doc-8/
SWITCH = '1'
WORK_MODE = '2'
TEMP = '3'
BRIGHT = '4'
HUE = '5'
SAT = '6'

LIGHT_DPID = [SWITCH, WORK_MODE, TEMP, BRIGHT, HUE, SAT]
SWITCH_DPID = [SWITCH, ]
LANG = 'en'
API_DOMAIN = 'api-us.doiting.com'

# Cloud relay server (used instead of local TCP port 5555)
RELAY_HOST = '139.162.135.94'
RELAY_PORT = 8899

# Configuration keys
TOKEN_CONF = 'token'
DEVICE_KEYS_CONF = 'device_keys'