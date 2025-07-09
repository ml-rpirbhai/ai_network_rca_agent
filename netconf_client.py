import logging
import xmltodict

from ncclient import manager
from nsp_client import NspClient

from redis_client import RedisClient

log = logging.getLogger(__name__)

redis_client = RedisClient()

"""
* Called by Gemini Agent *
"""
def get_cisco_ios_xr_interface_name_fn(ne_id:str, snmp_index:int) -> str:
    args = [ne_id, snmp_index]
    # Check redis
    interface_name = redis_client.get_return_value('get_cisco_ios_xr_interface_name_fn', args)

    if interface_name is None:
        nc_client = Client(ne_id, username='admin', password='Mainstreet5')
        interface_name = nc_client.get_cisco_ios_xr_interface_name(snmp_index)

        # Store in redis
        redis_client.store_call('get_cisco_ios_xr_interface_name_fn', args, interface_name)

    return interface_name


class Client:
    def __init__(self, ne_id, username, password):
        mgmt_ip_addr = NspClient.get_ne_details(ne_id)['mgmt_ip_addr']

        self.ncClientManager = manager.connect(host=mgmt_ip_addr, port='830', username=username,
                                               password=password, hostkey_verify=False)

    def _get(self, filter):
        netconf_response = self.ncClientManager.get(filter)
        return netconf_response

    """
    Given an interface SNMP ifindex, get the interface name.
    Params: snmp_index:  int
    Returns: str e.g. 'GigabitEthernet0/0/0/2', 'tunnel-te23601'.
    """
    def get_cisco_ios_xr_interface_name(self, snmp_index:int) -> str:
        filter = f"""<filter><snmp-agent-oper:snmp xmlns:snmp-agent-oper="http://cisco.com/ns/yang/Cisco-IOS-XR-snmp-agent-oper">
                       <snmp-agent-oper:interfaces>
                         <snmp-agent-oper:interface>
                           <snmp-agent-oper:interface-index>{snmp_index}</snmp-agent-oper:interface-index>
                         </snmp-agent-oper:interface>
                       </snmp-agent-oper:interfaces>
                     </snmp-agent-oper:snmp></filter>"""

        response = self._get(filter)
        log.debug(response)
        return xmltodict.parse(response.xml)['rpc-reply']['data']['snmp']['interfaces']['interface']['name']


"""
Test
"""
if __name__ == "__main__":
    my_nsp_client = NspClient(server='135.121.156.104')
    print(get_cisco_ios_xr_interface_name_fn('38.120.234.239', 16))