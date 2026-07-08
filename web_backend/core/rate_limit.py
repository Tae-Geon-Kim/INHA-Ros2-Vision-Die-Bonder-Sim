from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Duration, Limiter, Rate


def create_rate_limiter(times: int, seconds: int):
    limiter = Limiter(Rate(times, seconds * Duration.SECOND))

    return RateLimiter(limiter)
