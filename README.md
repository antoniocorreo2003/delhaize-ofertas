# Ofertas Delhaize

Panel: https://antoniocorreo2003.github.io/delhaize-ofertas/

- `ofertas.py`: descarga todas las promos de delhaize.be (1 vez al día, ≥ 6:00), calcula el precio real por unidad y avisa por ntfy de favoritos y palabras vigiladas.
- `docs/`: el panel (GitHub Pages). Los favoritos se mandan desde el panel a `ntfy.sh/<fav_topic>` (ver `docs/config.json`) y el bot los aplica cada 2 h en `docs/favoritos.json`.
- Secreto `NTFY_TOPIC`: topic privado de los avisos.
- Si Delhaize cambia su web y deja de funcionar, lo normal es que cambie el `HASH` de la consulta `ProductList` (se ve en las peticiones a `/api/v1/` de la página de promociones).
