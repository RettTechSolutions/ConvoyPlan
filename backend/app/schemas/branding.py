from pydantic import BaseModel, Field


class BrandingResponse(BaseModel):
    app_name: str
    logo_main_url: str | None
    logo_horizontal_url: str | None
    color_primary: str
    color_primary_hover: str
    color_accent: str
    color_bg: str
    color_surface: str
    color_nav_bg: str
    color_nav_text: str
    color_text: str
    color_text_muted: str


class BrandingUpdate(BaseModel):
    app_name: str = Field(min_length=1, max_length=100)
    color_primary: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_primary_hover: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_accent: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_bg: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_surface: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_nav_bg: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_nav_text: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_text: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_text_muted: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
