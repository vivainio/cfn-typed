import json
from typing import Any

import pytest

import cfn_typed as cfn
from cfn_typed.cli import parse_template
from cfn_typed.comments import comment_of


def _template() -> dict[str, Any]:
    queue = {"Type": "AWS::SQS::Queue", "Properties": {"VisibilityTimeout": 60}}
    return {
        "Parameters": {"Stage": {"Type": "String"} @ cfn.note("dev, test or prod")},
        "Resources": {
            "Jobs": queue @ cfn.note("Receives order events"),
            "Dlq": {"Type": "AWS::SQS::Queue"} @ cfn.note(["Poison messages", "Keep for 14 days"]),
        },
    }


def test_a_comment_goes_above_its_key() -> None:
    text = cfn.to_yaml(_template())
    assert "  # dev, test or prod\n  Stage:\n" in text
    assert "  # Receives order events\n  Jobs:\n" in text
    assert "  # Poison messages\n  # Keep for 14 days\n  Dlq:\n" in text


def test_the_comments_change_nothing_else() -> None:
    plain = {"Parameters": {"Stage": {"Type": "String"}}, "Resources": {"Jobs": {"Type": "AWS::SQS::Queue", "Properties": {"VisibilityTimeout": 60}}, "Dlq": {"Type": "AWS::SQS::Queue"}}}
    commented = _template()
    assert commented == plain
    assert cfn.to_json(commented) == cfn.to_json(plain) == json.dumps(plain, indent=2)
    assert parse_template(cfn.to_yaml(commented)) == plain  # a comment is not data


def test_the_original_is_not_changed() -> None:
    queue = {"Type": "AWS::SQS::Queue"}
    marked = queue @ cfn.note("hello")
    assert comment_of(queue) == () and comment_of(marked) == ("hello",)
    assert type(queue) is dict


def test_comments_stack_and_indent_with_their_depth() -> None:
    props = {"A": 1 @ cfn.note("one"), "B": ["x", "z" @ cfn.note("the second")] @ cfn.note("list")}
    text = cfn.to_yaml({"Resources": {"R": {"Type": "T", "Properties": props @ cfn.note("first") @ cfn.note("second")}}})
    assert "    # first\n    # second\n    Properties:\n" in text
    assert "      # one\n      A: 1\n" in text
    assert "      # list\n      B:\n" in text
    assert "        - x\n        # the second\n        - z\n" in text


def test_a_comment_above_a_list_item_that_is_a_mapping() -> None:
    tags = [{"Key": "a", "Value": "1"}, {"Key": "b", "Value": "2"} @ cfn.note("owner")]
    text = cfn.to_yaml({"Tags": tags})
    assert text == "Tags:\n  - Key: a\n    Value: '1'\n  # owner\n  - Key: b\n    Value: '2'\n"


def test_a_commented_intrinsic_keeps_its_short_form() -> None:
    text = cfn.to_yaml({"Resources": {"R": {"Arn": cfn.get_att("Q", "Arn") @ cfn.note("the queue")}}})
    assert "    # the queue\n    Arn: !GetAtt Q.Arn\n" in text


def test_the_first_key_can_carry_one_too() -> None:
    assert cfn.to_yaml({"A": 1 @ cfn.note("top")}) == "# top\nA: 1\n"
    assert cfn.to_yaml({"M": {"A": {"B": 1} @ cfn.note("inner first")}}) == "M:\n  # inner first\n  A:\n    B: 1\n"


def test_a_string_and_a_number_carry_a_comment_but_a_bool_cannot() -> None:
    assert comment_of("x" @ cfn.note("s")) == ("s",) and "x" @ cfn.note("s") == "x"
    assert comment_of(2.5 @ cfn.note("f")) == ("f",)
    with pytest.raises(TypeError, match="bool"):
        _ = True @ cfn.note("no")
    with pytest.raises(TypeError, match="NoneType"):
        _ = None @ cfn.note("no")


def test_a_comment_can_hold_several_lines_in_one_string() -> None:
    assert cfn.to_yaml({"A": 1 @ cfn.note("one\ntwo")}) == "# one\n# two\nA: 1\n"


def test_yaml_one_one_words_stay_quoted_and_are_read_back_the_same() -> None:
    template = {"On": "yes", "Off": "no", "Null": "~", "Port": "80", "Day": "2024-01-02", "Hex": "0x1F", "Float": "1.5", "Empty": "", "It's": "it's"}
    text = cfn.to_yaml(template)
    assert "'On': 'yes'" in text or "On: 'yes'" in text
    assert parse_template(text) == template


def test_the_loader_reads_yaml_one_one_booleans() -> None:
    assert parse_template("A: yes\nOn: x\nB: 0x1F\n") == {"A": True, True: "x", "B": 31}


def test_a_blank_line_inside_a_note_stays_a_bare_hash() -> None:
    assert cfn.to_yaml({"A": 1 @ cfn.note("one\n\ntwo")}) == "# one\n#\n# two\nA: 1\n"
    assert cfn.to_yaml({"A": 1 @ cfn.note(["one", "", "two"])}) == "# one\n#\n# two\nA: 1\n"


def test_blank_lines_at_the_ends_and_an_empty_note_write_nothing() -> None:
    assert cfn.to_yaml({"A": 1 @ cfn.note("\n\none\n\n")}) == "# one\nA: 1\n"
    assert cfn.to_yaml({"A": 1 @ cfn.note("")}) == "A: 1\n"


def test_windows_line_ends_and_trailing_spaces_are_dropped() -> None:
    assert cfn.to_yaml({"A": 1 @ cfn.note("a  \r\nb")}) == "# a\n# b\nA: 1\n"


def test_a_multi_line_value_keeps_its_block_scalar_with_a_note_above() -> None:
    script = "#!/bin/bash\necho hi\n"
    text = cfn.to_yaml({"Body": script @ cfn.note("runs on boot")})
    assert text == "# runs on boot\nBody: |\n  #!/bin/bash\n  echo hi\n"
    assert parse_template(text) == {"Body": script}


def test_a_triple_quoted_note_is_dedented_but_keeps_its_relative_indent() -> None:
    text = cfn.to_yaml({"A": 1 @ cfn.note("""
        Receives order events.
          indented example
        Owner: orders.
    """)})
    assert text == "# Receives order events.\n#   indented example\n# Owner: orders.\nA: 1\n"
    assert cfn.to_yaml({"A": 1 @ cfn.note("a\n    b")}) == "# a\n#     b\nA: 1\n"
