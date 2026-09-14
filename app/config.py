from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    cors_origins: str = "http://localhost:5173"

    environment: str = "development"
    secret_key: str

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")
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

    upload_dir: str = "/var/lib/relay/uploads"
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_max_files: int = 5

    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "Relay desk"
    smtp_timeout: int = 20
    # safety valve: only these addresses/domains receive mail.
    # "*" disables the guard entirely — do not set that until sending is proven.
    smtp_allowlist: str = ""
    app_base_url: str = "http://127.0.0.1:5173"

    @property
    def allowlist(self) -> list[str]:
        return [a.strip().lower() for a in self.smtp_allowlist.split(",") if a.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
