import functools
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
    wk_to_anonymous = {}
    anonymous_to_wk = {}

    regexps_list = None

    def __new__(cls):
        if cls.__instance is None:
            cls.__instance = super(AnonymizerSingleton, cls).__new__(cls)
        return cls.__instance

    def __init__(self):
        if not self.__initialized:
            # Load the regexp rules
            with open(REGEXP_CONFIG_YML_PATH, 'r') as stream:
                yml_config = yaml.load(stream, Loader=yaml.FullLoader)
                self.regexps_list = yml_config['regexps']
                #print(f"self.regexps_list: {self.regexps_list}")

            self.__initialized = True

    def _generate_anonymous(self, length=8):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def wellknown_to_anonymous(self, wellknown):
        if wellknown not in AnonymizerSingleton.wk_to_anonymous:
            anon = self._generate_anonymous()
            # Ensure no collisions
            while anon in AnonymizerSingleton.anonymous_to_wk:
                anon = self._generate_anonymous()
            AnonymizerSingleton.wk_to_anonymous[wellknown] = anon
            AnonymizerSingleton.anonymous_to_wk[anon] = wellknown
            log.debug(f"Updated wellknown_to_anonymous: {self.wk_to_anonymous}")
        return AnonymizerSingleton.wk_to_anonymous[wellknown]

    def anonymous_to_wellknown(self, anonymous):
        return AnonymizerSingleton.anonymous_to_wk.get(anonymous, None)

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
        for anon, wk in AnonymizerSingleton.anonymous_to_wk.items():
            s = s.replace(anon, wk)
        return s

    """
    LangChain Function Decorator:
    LLM calls func with anonymized args: Therefore must restore to call tools.
    Func returns tools response to LLM: Therefore must re-anonymize* the retval.
      * : Note that we must simply look up wk_to_anonymous: If any words in the retval are NOT in wk_to_anonymous, 
          we will NOT anonymize them because they were not anonymized in the alarm stream to begin with.
          (We can enhance this in the future)
    """
    def restore_then_reanonymize(cls, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Restore the args/kwargs to wk before calling the tool
            restored_args = tuple(cls.anonymous_to_wk.get(arg, arg) for arg in args)
            print(restored_args)
            restored_kwargs = {
                k: cls.anonymous_to_wk.get(v, v) for k, v in kwargs.items()
            }
            print(restored_kwargs)

            # Call the tool with the restored args/kwargs
            ret_val = func(*restored_args, **restored_kwargs)
            print(f"{func.__name__}({restored_args}) -> {ret_val}")

            # Re-anonymize ret_val
            if ret_val is not None:
                if isinstance(ret_val, str):
                    for wk, anon in cls.wk_to_anonymous.items():
                        ret_val = ret_val.replace(wk, anon)
                else:
                    error_msg = f"Unsupported instance {ret_val}"
                    print(error_msg)
                    raise RuntimeError(error_msg)

            return ret_val
        return wrapper

"""
Test
"""
if __name__ == '__main__':
    anonymizer = AnonymizerSingleton()

    alarm_feed = [
"2025-05-12T18:32:02.760893587Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:service:Site:/service[service-id='411'] | Interface toCE is not operational",
"2025-05-12T18:32:01.672731026Z | sim234_236 | fdn:app:mdm-ami-cmodel:100.2.3.4:/openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state:/router[router-name='Base']/bgp/neighbor[ip-address='FFC0:1::1'] | (ASN 200) VR 1: Group iBGP: Peer FFC0:1::1: received notification: code CEASE subcode CONN_REJECT",
"2025-05-20T19:49:34.586318210Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c3/1'] | Interface 1/1/c3/1 is not operational",
"2025-05-20T19:49:34.586318210Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:equipment:Equipment:/port[port-id='1/1/c3/1'] | Interface 1/1/c3/1 is not operational",
"2025-05-20T19:49:34.586033743Z | sim234_225 | fdn:app:mdm-ami-cmodel:2001::225:/openconfig-network-instance:network-instances/network-instance/interfaces/interface:/router[router-name='Base']/interface[interface-name='toSR236'] | Interface toSR236 is not operational"
]
    # Anonymize the alarm-feed
    for alarm in alarm_feed:
        #print(f"original: {alarm}")
        anon_alarm = anonymizer.anonymize_string(alarm)
        #print(f"anonymzd: {anon_alarm}")
        #restored_alarm = anonymizer.restore_anonymized_string(anon_alarm)
        #print(f"restored: {restored_alarm}")

    print(f"dict: {AnonymizerSingleton.wk_to_anonymous}")

    # Test the decorator on a toy tool
    @anonymizer.restore_then_reanonymize
    def test_tool(arg1) -> None:
        print(f"Passed in {arg1}")

    test_tool_arg = AnonymizerSingleton.wk_to_anonymous.get('sim234_225')
    print(f"Calling test_tool({test_tool_arg}) ...")
    test_tool(test_tool_arg)

