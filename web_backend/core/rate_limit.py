from collections import defaultdict, deque
from math import ceil
from time import monotonic

from fastapi import HTTPException, Request, status


_request_logs = defaultdict(deque)


def create_rate_limiter(times: int, seconds: int):
    async def limiter_dependency(
        request: Request,
    ):
        client_host = request.client.host if request.client else "unknown"
        key = f"rate-limit:{client_host}:{request.method}:{request.url.path}"
        now = monotonic()
        request_times = _request_logs[key]

        while request_times and now - request_times[0] >= seconds:
            request_times.popleft()

        if len(request_times) >= times:
            retry_after = max(1, ceil(seconds - (now - request_times[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"요청이 너무 많습니다. {retry_after}초 후 다시 시도해주세요.",
                headers={"Retry-After": str(retry_after)},
            )

        request_times.append(now)

    return limiter_dependency
