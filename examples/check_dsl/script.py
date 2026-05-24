from fritzconnection.lib.fritzstatus import FritzStatus
from fritzconnection.core.fritzconnection import FritzConnection

fc = FritzConnection(address="192.168.178.1", password="Pa$$w0rd")

def get_wan_mode(fc):
    link = fc.call_action("WANCommonInterfaceConfig:1", "GetCommonLinkProperties")
    access_type = link.get("NewWANAccessType", "")

    dsl = fc.call_action("WANDSLInterfaceConfig:1", "GetInfo")
    dsl_status = dsl.get("NewStatus", "")

    is_dsl_down = dsl_status not in ("Up", "ShowTime")
    is_lte = "LTE" in access_type or access_type == "X_AVM-DE_LTE"

    return {
        "access_type": access_type,   # "DSL" or "X_AVM-DE_LTE"
        "dsl_status": dsl_status,
        "dsl_down": is_dsl_down,
        "using_4g_fallback": is_lte or (is_dsl_down),
    }
	
print(get_wan_mode(fc=fc))