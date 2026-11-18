import logging
import time


logger = logging.getLogger(__name__)

class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()

        try:
            response = self.get_response(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                '%s %s failed in %.2f ms',
                request.method,
                request.path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response['X-Request-Duration-Ms'] = f'{duration_ms:.2f}'
        logger.info(
            '%s %s %s %.2f ms',
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response
