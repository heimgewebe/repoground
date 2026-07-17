
import pytest
import datetime
from merger.repoground.core import clock

def test_clock_now_utc_is_aware_and_utc():
    """Ensure now_utc() returns timezone-aware UTC datetime."""
    now = clock.now_utc()
    assert now.tzinfo == datetime.timezone.utc

def test_clock_frozen_context_restores_previous_state():
    """Ensure nested frozen contexts restore previous state correctly."""
    t1 = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    t2 = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    # Freezing with t1
    with clock.frozen(t1):
        assert clock.now_utc() == t1

        # Nested freezing with t2
        with clock.frozen(t2):
            assert clock.now_utc() == t2

        # Should restore to t1
        assert clock.now_utc() == t1

    # After exiting context, time should not be t1 anymore
    assert clock.now_utc() != t1

def test_clock_freeze_time_none_resets_to_system_time():
    """Ensure freeze_time(None) unfreezes the clock."""
    t1 = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    clock.freeze_time(t1)
    assert clock.now_utc() == t1

    clock.freeze_time(None)

    # Should be back to system time (or at least not frozen to t1)
    now = clock.now_utc()
    assert now.tzinfo == datetime.timezone.utc
    assert now != t1

def test_clock_rejects_non_strict_utc():
    """Ensure non-UTC datetimes are rejected."""
    # Naive datetime
    naive = datetime.datetime(2023, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="must be strictly UTC"):
        clock.freeze_time(naive)

    with pytest.raises(ValueError, match="must be strictly UTC"):
        with clock.frozen(naive):
            pass

    # Non-UTC timezone (e.g. fixed offset that isn't strictly timezone.utc object check)
    offset = datetime.timezone(datetime.timedelta(hours=1))
    other_tz = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=offset)

    with pytest.raises(ValueError, match="must be strictly UTC"):
        clock.freeze_time(other_tz)
