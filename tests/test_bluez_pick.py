import unittest

from omyphone.bluez import HFP_AG_UUID, pick_phone

ADAPTER = "/org/bluez/hci0"


def device(address, paired=True, connected=False, uuids=(HFP_AG_UUID,), name="Phone"):
    return {"org.bluez.Device1": {"Address": address, "Alias": name, "Paired": paired,
                                  "Connected": connected, "Adapter": ADAPTER, "UUIDs": list(uuids)}}


def objects(*devices, powered=True):
    result = {ADAPTER: {"org.bluez.Adapter1": {"Powered": powered}}}
    for i, dev in enumerate(devices):
        result[f"{ADAPTER}/dev_{i}"] = dev
    return result


class PickPhoneTests(unittest.TestCase):
    def test_first_paired_hfp_device(self):
        status, path = pick_phone(objects(device("11:11", uuids=["0000110b-0000-1000-8000-00805f9b34fb"]),
                                          device("22:22", connected=True, name="iPhone")), None)
        self.assertEqual(status, {"found": True, "address": "22:22", "name": "iPhone",
                                  "connected": True, "powered": True})
        self.assertEqual(path, f"{ADAPTER}/dev_1")

    def test_unpaired_phone_is_ignored(self):
        status, path = pick_phone(objects(device("22:22", paired=False)), None)
        self.assertFalse(status["found"])
        self.assertIsNone(path)

    def test_address_setting_wins_and_ignores_case(self):
        status, _ = pick_phone(objects(device("11:11"), device("AA:BB")), "aa:bb")
        self.assertEqual(status["address"], "AA:BB")

    def test_address_setting_without_match(self):
        status, path = pick_phone(objects(device("11:11")), "AA:BB")
        self.assertEqual((status["found"], status["address"], path), (False, "AA:BB", None))

    def test_adapter_power_reported_without_phone(self):
        self.assertFalse(pick_phone(objects(powered=False), None)[0]["powered"])
        self.assertTrue(pick_phone(objects(), None)[0]["powered"])

    def test_no_bluez_at_all(self):
        status, path = pick_phone({}, None)
        self.assertEqual((status["found"], status["powered"], path), (False, False, None))


if __name__ == "__main__":
    unittest.main()
