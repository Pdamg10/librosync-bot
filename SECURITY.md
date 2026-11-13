# Seguridad de LibroSync

## Secretos

- Nunca subas `backend/.env`, bases de datos SQLite ni logs a Git.
- `backend/.env` debe tener permisos `600` en el servidor.
- Si un token de Telegram o una API key se expone, revócalo inmediatamente:
  - Telegram: BotFather → `/revoke`.
  - Gemini: Google AI Studio → API keys.
  - GitHub: Settings → Developer settings → Personal access tokens.

## Reportar una vulnerabilidad

No abras un issue público con detalles explotables. Contacta al mantenedor del
repositorio por el canal privado indicado en el perfil de GitHub.
