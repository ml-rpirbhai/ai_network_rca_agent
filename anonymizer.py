import logging
import random
import re
import string
import yaml

log = logging.getLogger(__name__)

REGEXP_CONFIG_YML_PATH = 'config/anonymizer.yaml'

class AnonymizerSingleton:
    __instance = None
    __initialized = False

    regexps_list = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super(AnonymizerSingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            self._init_maps()

            # Load the regexp rules
            with open(REGEXP_CONFIG_YML_PATH, 'r') as stream:
                yml_config = yaml.load(stream, Loader=yaml.FullLoader)
                self.regexps_list = yml_config['regexps']
                #print(f"self.regexps_list: {self.regexps_list}")

            self.__initialized = True

    def _init_maps(self):
        self.wk_to_anonymous = {}
        self.anonymous_to_wk = {}

    def _generate_anonymous(self, length=8):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def wellknown_to_anonymous(self, wellknown):
        if wellknown not in self.wk_to_anonymous:
            anon = self._generate_anonymous()
            # Ensure no collisions
            while anon in self.anonymous_to_wk:
                anon = self._generate_anonymous()
            self.wk_to_anonymous[wellknown] = anon
            self.anonymous_to_wk[anon] = wellknown
            log.debug(f"Updated wellknown_to_anonymous: {self.wk_to_anonymous}")
        return self.wk_to_anonymous[wellknown]

    def anonymous_to_wellknown(self, anonymous):
        return self.anonymous_to_wk.get(anonymous, None)

    """
    Anonymizes every word in the string that matches regexp group 0
    """
    def anonymize_string(self, s: str):
        for regexp in self.regexps_list:
            def replace_fn(match):
                wellknown = match.group(0)
                return self.wellknown_to_anonymous(wellknown)
            s = re.sub(regexp, replace_fn, s)
        return s

    """
    Restores every anonymized word in the string with the original (well-known) word
    """
    def restore_anonymized_string(self, s):
        for anon, wk in self.anonymous_to_wk.items():
            s = s.replace(anon, wk)
        return s


"""
Test
"""
if __name__ == '__main__':
    anonymizer = AnonymizerSingleton()
    #wellknown_str = 'router_A'
    #anonymous_str = anonymizer.wellknown_to_anonymous(wellknown_str)
    #print(f"{wellknown_str} -> {anonymous_str}")
    #wellknown_str = anonymizer.anonymous_to_wellknown(anonymous_str)
    #print(f"{anonymous_str} -> {wellknown_str}")

    """
    Anonymize select words in a string
    """
    vrf_if_str_list = [
"2025-05-12T18:32:02.760893587Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='411'] | Interface toCE is not operational",
"2025-05-12T18:32:01.672731026Z | sim234_236 | fdn:app:mdm-ami-cmodel:100.2.3.4:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='FFC0:1::1'] | (ASN 200) VR 1: Group iBGP: Peer FFC0:1::1: received notification: code CEASE subcode CONN_REJECT",
"2025-05-20T19:49:34.586318210Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c3/1'] | Interface 1/1/c3/1 is not operational",
"2025-05-20T19:49:34.586318210Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c3/1'] | Interface 1/1/c3/1 is not operational",
"2025-05-20T19:49:34.586033743Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:/openconfig-network-instance:network-instances/network-instance/interfaces/interface:/router[router-name='Base']/interface[interface-name='toSR236'] | Interface toSR236 is not operational"
]
    for vrf_if_str in vrf_if_str_list:
        print(f"original: {vrf_if_str}")
        anon_vrf_if_str = anonymizer.anonymize_string(vrf_if_str)
        print(f"anonymzd: {anon_vrf_if_str}")
        restored_vrf_if_str = anonymizer.restore_anonymized_string(anon_vrf_if_str)
        print(f"restored: {restored_vrf_if_str}")
        #print(f"dict: {anonymizer.wk_to_anonymous}")
