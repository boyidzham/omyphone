import time
import unittest
from pathlib import Path

from omyphone import vcard

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text()


def contacts(text):
    return vcard.contacts_from_cards(vcard.parse_cards(text))


class ParseCardsTests(unittest.TestCase):
    def test_splits_cards(self):
        self.assertEqual(len(vcard.parse_cards(fixture("pb.vcf"))), 8)

    def test_crlf_and_folded_lines(self):
        text = fixture("pb.vcf").replace("\n", "\r\n")
        cards = vcard.parse_cards(text)
        photo = next(v for n, _p, v in cards[1] if n == "PHOTO")
        self.assertTrue(photo.endswith("NDL/"))  # the folded second line was joined
        self.assertEqual(len(cards), 8)

    def test_empty_text_has_no_cards(self):
        self.assertEqual(vcard.parse_cards(""), [])

    def test_text_outside_cards_is_ignored(self):
        self.assertEqual(vcard.parse_cards("garbage\nTEL:123\n"), [])

    def test_group_prefix_is_dropped(self):
        cards = vcard.parse_cards("BEGIN:VCARD\nitem1.TEL;TYPE=CELL:0123\nEND:VCARD\n")
        self.assertEqual(cards[0][0][0], "TEL")


class ContactsTests(unittest.TestCase):
    def setUp(self):
        self.contacts = contacts(fixture("pb.vcf"))
        self.by_name = {c["name"]: c for c in self.contacts}

    def test_names_and_numbers(self):
        self.assertEqual(self.by_name["Ali Ahmad"]["numbers"], [{"number": "+60123456789", "label": "Mobile"}])

    def test_two_numbers_keep_order_and_labels(self):
        self.assertEqual(self.by_name["Siti Aminah"]["numbers"],
                         [{"number": "012 345 6780", "label": ""},
                          {"number": "+60 (3) 2345-6789", "label": "Home"}])

    def test_utf8_name_and_work_label(self):
        self.assertEqual(self.by_name["陈小明"]["numbers"][0]["label"], "Work")

    def test_escaped_comma_in_name(self):
        self.assertIn("Kedai Runcit, Pak Abu", self.by_name)

    def test_name_from_n_when_fn_missing(self):
        self.assertIn("Mei Ling Lim", self.by_name)

    def test_contact_without_number_is_dropped(self):
        self.assertNotIn("No Number Person", self.by_name)

    def test_photo_and_email_are_not_kept(self):
        self.assertEqual(set(self.by_name["Ali Ahmad"]), {"name", "numbers"})

    def test_org_when_no_name(self):
        text = "BEGIN:VCARD\nVERSION:3.0\nORG:Kedai Runcit;Cawangan\\; Satu\nTEL:0388887777\nEND:VCARD\n"
        self.assertEqual(contacts(text)[0]["name"], "Kedai Runcit")

    def test_empty_name_when_no_name_at_all(self):
        # Not the number: the UI shows the number itself, and a fake name would show it twice.
        text = "BEGIN:VCARD\nVERSION:3.0\nTEL:0388887777\nEND:VCARD\n"
        self.assertEqual(contacts(text)[0], {"name": "", "numbers": [{"number": "0388887777", "label": ""}]})

    def test_vcard21_quoted_printable_does_not_crash(self):
        text = ("BEGIN:VCARD\r\nVERSION:2.1\r\nN;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:=C3=81li;;;;\r\n"
                "TEL;CELL;VOICE:+60123456789\r\nEND:VCARD\r\n")
        result = contacts(text)
        self.assertEqual(result[0]["numbers"], [{"number": "+60123456789", "label": "Mobile"}])

    def test_vcard21_quoted_printable_name_is_decoded(self):
        text = ("BEGIN:VCARD\r\nVERSION:2.1\r\nN;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:=E9=99=88;=E5=B0=8F=E6=98=8E;;;\r\n"
                "TEL;CELL:0123\r\nEND:VCARD\r\n")
        self.assertEqual(contacts(text)[0]["name"], "小明 陈")

    def test_quoted_printable_soft_line_break_is_joined(self):
        text = ("BEGIN:VCARD\r\nVERSION:2.1\r\nFN;CHARSET=UTF-8;QUOTED-PRINTABLE:=C3=81li =\r\n"
                "Ahmad=20bin=\r\n Abu\r\nTEL:0123\r\nEND:VCARD\r\n")
        self.assertEqual(contacts(text)[0]["name"], "Áli Ahmad bin Abu")

    def test_quoted_printable_in_another_charset(self):
        text = "BEGIN:VCARD\nVERSION:2.1\nFN;ENCODING=QUOTED-PRINTABLE;CHARSET=ISO-8859-1:Jos=E9\nTEL:0123\nEND:VCARD\n"
        self.assertEqual(contacts(text)[0]["name"], "José")

    def test_bad_quoted_printable_does_not_crash(self):
        text = "BEGIN:VCARD\nVERSION:2.1\nFN;QUOTED-PRINTABLE;CHARSET=NOPE:=ZZ=C3\nTEL:0123\nEND:VCARD\n"
        self.assertEqual(contacts(text)[0]["numbers"][0]["number"], "0123")

    def test_large_phonebook_is_fast(self):
        card = "BEGIN:VCARD\nVERSION:3.0\nFN:Person {i}\nTEL;TYPE=CELL:+6012{i:07d}\nEND:VCARD\n"
        text = "".join(card.format(i=i) for i in range(2000))
        started = time.monotonic()
        self.assertEqual(len(contacts(text)), 2000)
        self.assertLess(time.monotonic() - started, 1.0)


class HistoryTests(unittest.TestCase):
    def test_directions_names_and_order(self):
        entries = vcard.history_from_cards(vcard.parse_cards(fixture("cch.vcf")))
        self.assertEqual([e["direction"] for e in entries], ["outgoing", "missed", "incoming"])
        self.assertEqual([e["name"] for e in entries], ["Ali Ahmad", "", "Siti Aminah"])
        self.assertEqual(entries[1]["number"], "+60155556666")

    def test_sorted_newest_first(self):
        text = fixture("cch.vcf")
        cards = vcard.parse_cards(text)
        entries = vcard.history_from_cards(list(reversed(cards)))
        self.assertEqual(entries[0]["name"], "Ali Ahmad")

    def test_local_time(self):
        entries = vcard.history_from_cards(vcard.parse_cards(fixture("cch.vcf")))
        expected = int(time.mktime(time.strptime("20260928T101500", "%Y%m%dT%H%M%S")))
        self.assertEqual(entries[0]["start"], expected)

    def test_utc_time(self):
        self.assertEqual(vcard.parse_time("19700101T000100Z"), 60)

    def test_bad_time_is_none(self):
        self.assertIsNone(vcard.parse_time("yesterday"))

    def test_card_without_datetime_or_direction_is_dropped(self):
        text = ("BEGIN:VCARD\nTEL:1\nEND:VCARD\n"
                "BEGIN:VCARD\nTEL:2\nX-IRMC-CALL-DATETIME:20260928T101500\nEND:VCARD\n")
        self.assertEqual(vcard.history_from_cards(vcard.parse_cards(text)), [])

    def test_default_direction(self):
        text = "BEGIN:VCARD\nTEL:2\nX-IRMC-CALL-DATETIME:20260928T101500\nEND:VCARD\n"
        entries = vcard.history_from_cards(vcard.parse_cards(text), "missed")
        self.assertEqual(entries[0]["direction"], "missed")
