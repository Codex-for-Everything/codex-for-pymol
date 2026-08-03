import json
import unittest

from pymol_codex.serializer import to_jsonable


class DangerousRepr:
    def __repr__(self):
        raise AssertionError("repr must not be called")


class SerializerTests(unittest.TestCase):
    def test_unknown_values_do_not_call_repr(self):
        value = to_jsonable(DangerousRepr())
        self.assertTrue(value["_unserialized"])
        self.assertIn("DangerousRepr", value["_type"])

    def test_nonfinite_floats_remain_valid_json(self):
        value = to_jsonable(
            {"nan": float("nan"), "positive": float("inf"), "negative": float("-inf")}
        )
        encoded = json.dumps(value, allow_nan=False)
        self.assertIn('"_nonfinite_float"', encoded)

    def test_limits_items_and_strings(self):
        value = to_jsonable(list(range(10)), max_items=3)
        self.assertEqual(value[:3], [0, 1, 2])
        self.assertEqual(value[-1], {"_truncated": 7})
        self.assertEqual(to_jsonable("abcdef", max_string=3), "abc…")

    def test_sequence_limit_does_not_iterate_the_entire_value(self):
        class CountingList(list):
            iterations = 0

            def __iter__(self):
                for item in super().__iter__():
                    type(self).iterations += 1
                    yield item

        value = CountingList(range(5000))
        result = to_jsonable(value, max_items=3)
        self.assertEqual(CountingList.iterations, 4)
        self.assertEqual(result[-1], {"_truncated": 4997})


if __name__ == "__main__":
    unittest.main()
