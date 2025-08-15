from pydantic import BaseModel, EmailStr
from typing import List



class User(BaseModel):

    nickname: str
    email: EmailStr
    password: str
    picture: str


class UserProfile(User):

    profile_id: str
    friends: List[User]

