"""Guard v2 限流器单元测试。"""

from core.guard.ratelimit import RateLimiter


def test_parse():
    assert RateLimiter.parse("5/m") == (5, 60.0)
    assert RateLimiter.parse("100/h") == (100, 3600.0)
    assert RateLimiter.parse("bad") is None


def test_sliding_window_allows_within_limit():
    rl = RateLimiter()
    for _ in range(5):
        assert rl.check("git_status", "alice", "5/m") is True
    assert rl.check("git_status", "alice", "5/m") is False  # 第 6 次超限


def test_per_caller_isolated():
    rl = RateLimiter()
    for _ in range(5):
        rl.check("git_status", "alice", "5/m")
    assert rl.check("git_status", "bob", "5/m") is True  # bob 不受 alice 影响


def test_per_tool_isolated():
    rl = RateLimiter()
    for _ in range(5):
        rl.check("git_status", "alice", "5/m")
    assert rl.check("file_search", "alice", "5/m") is True


def test_invalid_rate_limit_passes():
    rl = RateLimiter()
    for _ in range(100):
        assert rl.check("x", "y", "??") is True


def test_reset():
    rl = RateLimiter()
    for _ in range(5):
        rl.check("git_status", "alice", "5/m")
    assert rl.reset("git_status") == 1
    assert rl.check("git_status", "alice", "5/m") is True
