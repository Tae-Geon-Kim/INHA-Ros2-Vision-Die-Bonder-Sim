from pydantic import BaseModel
from typing import Optional, Any

class CommonResponse(BaseModel):
    success: bool = True
    message: str =  "사용자의 요청이 성공적으로 수행되었습니다."
    data: Optional[Any] = None