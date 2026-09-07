from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    cors_origins: str = "http://localhost:5173"

    secret_key: str
    session_hours: int = 12
    cookie_secure: bool = False

    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base: str = ""
    ldap_user_filter: str = "(&(objectClass=inetOrgPerson)(mail={email}))"
    ldap_group_base: str = ""
    ldap_agent_group: str = ""
    ldap_attr_name: str = "displayName"
    ldap_attr_email: str = "mail"
    ldap_tls_verify: bool = True

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
