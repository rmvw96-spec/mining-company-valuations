"""The command line."""
import pytest

from minerval.__main__ import main, parse_today


def test_parse_today():
    assert parse_today(None) is None
    assert parse_today("gold=3859, silver=47.7,copper=5.99") == {"gold": 3859.0, "silver": 47.7, "copper": 5.99}
    with pytest.raises(ValueError):
        parse_today("gold:3859")


@pytest.mark.parametrize("argv", [[], ["no-such-command"]])
def test_bad_usage_exits(argv, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2


@pytest.mark.parametrize("cmd", ["prices", "fetch", "compute", "refresh", "financials", "fetch-history",
                                 "backtest", "project"])
def test_every_command_has_help(cmd, capsys):
    with pytest.raises(SystemExit) as e:
        main([cmd, "-h"])
    assert e.value.code == 0
    assert "usage" in capsys.readouterr().out
