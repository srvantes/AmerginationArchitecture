from typing import Optional

from pydantic import BaseModel, EmailStr
from typing import List



class User(BaseModel):

    nickname: Optional[str]
    email: Optional[EmailStr]
    password: Optional[str]

    access_right: str

class UserProfile(User):

    profile_id: str
    friends: List[User]

class Admin(User):
    pass

