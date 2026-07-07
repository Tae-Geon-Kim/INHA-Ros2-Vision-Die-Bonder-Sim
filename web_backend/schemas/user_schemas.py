import re
from pydantic import BaseModel, Field, field_validator

# 아이디 제약조건 검사
def validate_id_format(v: str)->str:

    v = v.strip()

    # 특수문자는 선택 사항으로 두면서, '영문자'와 '숫자'는 무조건 1개가 있는 5 ~ 30자
    pattern = r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d$!%*#?&._-]{5,30}$'

    if not re.match(pattern, v):
        raise ValueError("아이디 형식이 올바르지 않습니다. (영문자, 숫자가 포함된 5 ~ 30자)")
    return v

# 비밀번호 제약조건 검사
def validate_password_format(v: str)->str:

    # 영문 1개 이상 + 숫자 1개 이상 + 특수문자 1개 이상 필수인 8 ~ 30자 허용
    pattern = r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*#?&._-])[A-Za-z\d@$!%*#?&._-]{8,30}$'

    if not re.match(pattern, v):
        raise ValueError("비밀번호 형식이 올바르지 않습니다. (영문자, 숫자, 특수문자(@$!%*#?&._-)가 포함한 8 ~ 30자)")
    return v

class UserLogin(BaseModel):
    id: str = Field(..., min_length = 5, max_length = 30)
    password: str = Field(..., min_length = 8, max_length = 30)

    @field_validator('id')
    @classmethod
    def check_id(cls, v): return validate_id_format(v)

    @field_validator('password')
    @classmethod
    def check_pw(cls, v): return validate_password_format(v)
