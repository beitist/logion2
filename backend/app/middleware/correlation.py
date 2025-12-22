import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Context variable to store the request ID
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default=None)

def get_request_id() -> str:
    return request_id_ctx_var.get()

class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            # Prefer header, else generate new UUID
            request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
            
            # Set in context
            token = request_id_ctx_var.set(request_id)
            
            try:
                response = await call_next(request)
                # Ensure response is a valid Response object before setting headers
                # (Some specialized responses might handle this differently, but standard Starlette Response is fine)
                response.headers["X-Request-ID"] = request_id
                return response
            finally:
                # Clean up context
                request_id_ctx_var.reset(token)
                
        except Exception as e:
            # Fallback if something goes wrong in middleware itself
            # But usually we want to bubble up to exception handler
            raise e
