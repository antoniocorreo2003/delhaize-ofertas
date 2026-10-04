#!/usr/bin/env python3
"""
Bot de ofertas Delhaize.

1. Aplica los cambios de favoritos que manda el panel (vía ntfy).
2. Descarga TODAS las promociones de delhaize.be (una vez al día o si se fuerza).
3. Calcula el precio real por unidad de cada promo (1+1, 2ª a -50%, 3 por 5 €...).
4. Avisa al móvil (ntfy) de: semana nueva de ofertas y favoritos en oferta (con foto).
5. Escribe docs/ofertas.json y docs/favoritos.json, que lee el panel (GitHub Pages).
"""
import base64
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------- AJUSTES ----------------
PANEL_URL = "https://antoniocorreo2003.github.io/delhaize-ofertas/"
IDIOMA = "fr"                 # "fr" o "nl": idioma de los nombres de producto
HORA_DESCARGA = 6             # descarga completa 1 vez al día, a partir de esta hora (las ofertas cambian el jueves)
DIAS_HISTORIAL = 400          # cuánto historial de precios guardar
# -----------------------------------------

DIR = Path(__file__).parent
DOCS = DIR / "docs"
ESTADO = DIR / "estado.json"
HISTORIAL = DOCS / "historial.json"
OFERTAS = DOCS / "ofertas.json"
FAVORITOS = DOCS / "favoritos.json"
CONFIG = DOCS / "config.json"   # contiene el topic público de favoritos

TOPIC = os.environ.get("NTFY_TOPIC") or (DIR / "ntfy_topic.txt").read_text().strip()
FAV_TOPIC = json.loads(CONFIG.read_text())["fav_topic"]

API = "https://www.delhaize.be/api/v1/"
HASH = "ef54fc2d8da4a9ad4987b2fb18f61c59f341d018be0f4670b0c9c7dabff07e5c"
IMG = "https://static.delhaize.be"
WEB = "https://www.delhaize.be"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
BRU = ZoneInfo("Europe/Brussels")  # las fechas de Delhaize vienen en UTC

CATEGORIAS = {
    "v2FRU": "Fruta y verdura", "v2MEA": "Carne, pescado y veggie",
    "v2DAI": "Lácteos, huevos y queso", "v2BAK": "Panadería",
    "v2DRI": "Bebidas", "v2WIN": "Vinos y cava", "v2FRO": "Congelados",
    "v2EPI": "Despensa", "v2SNA": "Snacks y dulces", "v2BAB": "Bebé",
    "v2HYG": "Higiene y belleza", "v2HOU": "Hogar y limpieza",
    "v2PET": "Mascotas", "v2SPO": "Deporte y salud", "v2BIO": "Bio",
    "v2CHA": "Charcutería y platos", "v2TRA": "Platos preparados",
    "v2SWE": "Dulces y desayuno", "v2SAL": "Despensa", "v2CLE": "Hogar y limpieza",
    "V2ALC": "Cerveza y alcohol", "v2ALC": "Cerveza y alcohol",
}
CAT_FR = {  # por si el código cambia, traducimos por el nombre
    "fruits": "Fruta y verdura", "viande": "Carne, pescado y veggie",
    "produits laitiers": "Lácteos, huevos y queso", "boulangerie": "Panadería",
    "boissons": "Bebidas", "vins": "Vinos y cava", "surgel": "Congelados",
    "epicerie": "Despensa", "épicerie": "Despensa", "snack": "Snacks y dulces",
    "bébé": "Bebé", "bebe": "Bebé", "hygi": "Higiene y belleza",
    "beauté": "Higiene y belleza", "ménage": "Hogar y limpieza",
    "entretien": "Hogar y limpieza", "maison": "Hogar y limpieza",
    "animaux": "Mascotas", "sport": "Deporte y salud", "traiteur": "Charcutería y platos",
    "charcuterie": "Charcutería y platos", "repas": "Platos preparados",
    "bière": "Cerveza y alcohol", "alcool": "Cerveza y alcohol", "conserve": "Despensa",
    "vite et vraiment": "Platos preparados", "régime": "Dieta especial", "sucrée": "Dulces y desayuno",
    "salée": "Despensa", "frais": "Lácteos, huevos y queso",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def leer(p, defecto):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return defecto


def escribir(p, datos, compacto=False):
    Path(p).write_text(json.dumps(datos, ensure_ascii=False,
                                  separators=(",", ":") if compacto else None,
                                  indent=None if compacto else 1))


# ---------------- DELHAIZE ----------------
def pagina(n, por_pagina=50):
    v = {"productListingType": "PROMOTION_SEARCH", "lang": IDIOMA, "productCodes": "",
         "categoryCode": "", "excludedProductCodes": "", "brands": "", "keywords": "",
         "productTypes": "", "lazyLoadCount": por_pagina, "pageNumber": n,
         "sort": "categoryOrder", "searchQuery": "", "hideProductsWithoutPromo": False,
         "hideUnavailableProducts": True, "maxItemsToDisplay": 0,
         "includePotentialActivatableOffers": True, "customerSegment": "newPromoPageSegment"}
    ext = {"persistedQuery": {"version": 1, "sha256Hash": HASH}}
    url = API + "?" + urllib.parse.urlencode({
        "operationName": "ProductList",
        "variables": json.dumps(v, separators=(",", ":")),
        "extensions": json.dumps(ext, separators=(",", ":"))})
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "content-type": "application/json", "x-apollo-operation-name": "ProductList",
        "Accept-Language": "fr-BE,fr;q=0.9"})
    for intento in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
            if "data" in d and d["data"].get("productList"):
                return d["data"]["productList"]
            raise RuntimeError(str(d.get("errors"))[:300])
        except Exception as e:
            log(f"página {n} intento {intento + 1}: {e}")
            time.sleep(5 * (intento + 1))
    raise RuntimeError(f"No se pudo descargar la página {n}")


def descargar_todo():
    primera = pagina(0)
    total = primera["pagination"]["totalPages"]
    log(f"{primera['pagination']['totalResults']} productos en {total} páginas")
    productos = list(primera["products"])
    for n in range(1, total):
        productos += pagina(n)["products"]
        time.sleep(0.5)
    vistos, unicos = set(), []
    for p in productos:
        if p["code"] not in vistos:
            vistos.add(p["code"])
            unicos.append(p)
    return unicos


def num(texto):
    """'€12,59' -> 12.59 ; '186,53 €/kg' -> 186.53"""
    if not texto:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", texto.replace(" ", "").replace(" ", ""))
    return float(m.group(1).replace(",", ".")) if m else None


def fecha(s):
    """'07/10/2026 21:59:00' (UTC) -> ISO"""
    try:
        return datetime.strptime(s, "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        return None


def calcular_promo(precio, promo):
    """Devuelve (precio_unidad_efectivo, unidades_necesarias, tipo_simple)."""
    tipo = promo.get("promotionTypeCode") or ""
    msg = (promo.get("simplePromotionMessage") or promo.get("title") or "").lower()
    n = promo.get("qualifyingCount") or 1
    gratis = promo.get("freeCount")

    if "livraison" in msg or "levering" in msg:
        return None, n, "Envío gratis"
    m = re.search(r"-\s*€\s*(\d+(?:[.,]\d+)?)\D+(\d+)\s*produit", msg)  # - €2 à l'achat de 1 produit
    if m:
        euros, k = float(m.group(1).replace(",", ".")), int(m.group(2))
        if euros < precio * k:
            return round((precio * k - euros) / k, 2), k, f"-{euros:g}€" + (f" x{k}" if k > 1 else "")
    m = re.search(r"-\s*(\d+(?:[.,]\d+)?)\s*%\D*pour\s*(\d+)", msg)  # -66.66% pour 3 (sobre todos)
    if m:
        pct, k = float(m.group(1).replace(",", ".")), int(m.group(2))
        return round(precio * (1 - pct / 100), 2), k, f"-{round(pct)}% x{k}"
    m = re.search(r"(\d+)\s*\+\s*(\d+)", msg)  # 1+1, 2+1, 3+2...
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return round(precio * a / (a + b), 2), a + b, f"{a}+{b}"
    m = re.search(r"(\d+)\D{0,4}(?:ème|e|de)\s*à?\s*-?\s*(\d+)\s*%", msg)  # 2ème à -50%
    if m:
        k, pct = int(m.group(1)), int(m.group(2))
        return round(precio * (k - pct / 100) / k, 2), k, f"{k}ª -{pct}%"
    m = re.search(r"(\d+)\s*(?:produits?|pour|voor|stuks)?\D{0,12}?€\s*(\d+(?:[.,]\d+)?)", msg) \
        or re.search(r"(\d+)\s*(?:produits?)?\s*pour\s*(\d+(?:[.,]\d+)?)\s*€", msg)
    if m:  # 3 produits pour €5
        k, total = int(m.group(1)), float(m.group(2).replace(",", "."))
        if k > 0 and total < precio * k:
            return round(total / k, 2), k, f"{k} x {total:g}€"
    m = re.search(r"-\s*(\d+(?:[.,]\d+)?)\s*%", msg)
    if m:
        pct = round(float(m.group(1).replace(",", ".")))
        return round(precio * (1 - pct / 100), 2), n, f"-{pct}%"
    if gratis and n:
        return round(precio * (n - gratis) / n, 2), n, f"{n - gratis}+{gratis}"
    return None, n, promo.get("simplePromotionMessage") or tipo


def categoria(p):
    c = p.get("firstLevelCategory") or {}
    if c.get("code") in CATEGORIAS:
        return CATEGORIAS[c["code"]]
    nombre = (c.get("name") or "").lower()
    for k, v in CAT_FR.items():
        if k in nombre:
            return v
    return c.get("name") or "Otros"


def imagen(p, formato="respListGrid"):
    imgs = p.get("images") or []
    for f in (formato, "small", "zoom"):
        for i in imgs:
            if i.get("format") == f and i.get("url"):
                return IMG + i["url"]
    return IMG + imgs[0]["url"] if imgs else ""


def simplificar(p):
    pr = p.get("price") or {}
    precio = pr.get("value") or num(pr.get("formattedValue"))
    if not precio:
        return None
    promos = [x for x in (p.get("potentialPromotions") or []) if x.get("toDisplay", True)]
    promos += [x for x in (p.get("potentialActivatablePromotions") or []) if x]
    mejor = None
    for promo in promos:
        efectivo, uds, tipo = calcular_promo(precio, promo)
        cand = {"ef": efectivo, "uds": uds, "tipo": tipo,
                "txt": promo.get("simplePromotionMessage") or promo.get("title") or "",
                "fin": fecha(promo.get("endDate")), "ini": fecha(promo.get("startDate")),
                "online": bool(promo.get("onlineOnly")),
                "tarjeta": promo.get("redemptionLevel") == "MEMBER" or bool(promo.get("offerId")),
                "id": promo.get("code")}
        if mejor is None or (cand["ef"] or precio) < (mejor["ef"] or precio):
            mejor = cand
    if mejor is None:
        return None
    # Algunas promos ya vienen aplicadas en el precio tachado
    tachado = num(pr.get("discountedPriceFormatted")) if pr.get("showStrikethroughPrice") else None
    if mejor["ef"] is None and tachado and tachado < precio:
        mejor["ef"] = tachado
    ef = mejor["ef"] or precio
    desc = round(100 * (1 - ef / precio)) if precio else 0
    kg = num(pr.get("supplementaryPriceLabel1"))
    unidad = (re.search(r"€\s*/\s*(\w+)", pr.get("supplementaryPriceLabel1") or "") or [None, ""])[1]
    return {
        "c": p["code"], "n": p.get("name", "").strip(), "m": (p.get("manufacturerName") or "").strip(),
        "cat": categoria(p), "img": imagen(p), "imgL": imagen(p, "zoom"),
        "url": WEB + (p.get("url") or ""), "p": round(precio, 2), "ef": round(ef, 2),
        "d": desc, "uds": mejor["uds"], "tipo": mejor["tipo"], "txt": mejor["txt"],
        "fin": mejor["fin"], "ini": mejor["ini"], "online": mejor["online"],
        "tarjeta": mejor["tarjeta"], "pid": mejor["id"],
        "kg": kg, "kgU": unidad, "kgEf": round(kg * ef / precio, 2) if kg else None,
        "fmt": pr.get("supplementaryPriceLabel2") or "",
        "bio": any("bio" in (b.get("code") or "") for b in (p.get("badges") or [])),
        "ns": p.get("nutriScoreLetter"), "top": p.get("bestSellerScore") or 0,
    }


# ---------------- NTFY ----------------
def ntfy(titulo, texto, tags="shopping_cart", prioridad=3, click=PANEL_URL, foto=None):
    if not TOPIC:
        log("[ntfy] sin topic")
        return
    if os.environ.get("SIN_AVISOS"):
        log(f"[ntfy desactivado] {titulo}")
        return
    h = {"Title": titulo, "Tags": tags, "Priority": str(prioridad), "Click": click, "Markdown": "yes"}
    if foto:
        h["Attach"] = foto
    # ntfy acepta cabeceras UTF-8 con el formato RFC 2047
    h = {k: (f"=?UTF-8?B?{base64.b64encode(v.encode()).decode()}?="
             if any(ord(ch) > 127 for ch in v) else v) for k, v in h.items()}
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=texto.encode(), headers=h)
        urllib.request.urlopen(req, timeout=20).read()
        log(f"[ntfy] {titulo}")
    except Exception as e:
        log(f"[ntfy] error {e}")


# ---------------- FAVORITOS ----------------
def sincronizar_favoritos(estado):
    """El panel publica cambios en ntfy.sh/<fav_topic>. ntfy guarda 12 h, el bot corre cada 2 h."""
    favs = leer(FAVORITOS, {"productos": {}, "palabras": [], "aplicado": 0})
    desde = estado.get("fav_desde", "all")  # timestamp unix del último cambio leído
    try:
        with urllib.request.urlopen(f"https://ntfy.sh/{FAV_TOPIC}/json?poll=1&since={desde}",
                                    timeout=30) as r:
            lineas = r.read().decode().splitlines()
    except Exception as e:
        log(f"[favoritos] no se pudo leer ntfy: {e}")
        return favs, False
    cambios = 0
    for linea in lineas:
        try:
            ev = json.loads(linea)
            if ev.get("event") != "message":
                continue
            op = json.loads(ev["message"])
        except Exception:
            continue
        estado["fav_desde"] = str(ev["time"])
        t = op.get("t") or ev.get("time", 0) * 1000
        if t <= favs.get("aplicado", 0):
            continue  # ya aplicado en una ejecución anterior
        accion = op.get("a")
        if accion == "add" and op.get("c"):
            p = op.get("p") or {}
            favs["productos"][op["c"]] = {k: str(p.get(k, ""))[:300] for k in ("n", "m", "img", "url", "cat")}
            favs["productos"][op["c"]]["desde"] = datetime.now().strftime("%Y-%m-%d")
        elif accion == "del" and op.get("c"):
            favs["productos"].pop(op["c"], None)
        elif accion == "kw+" and op.get("k"):
            k = op["k"].strip().lower()[:40]
            if k and k not in favs["palabras"]:
                favs["palabras"].append(k)
        elif accion == "kw-" and op.get("k"):
            favs["palabras"] = [x for x in favs["palabras"] if x != op["k"].strip().lower()]
        else:
            continue
        favs["aplicado"] = max(favs.get("aplicado", 0), int(t))
        cambios += 1
    if cambios:
        log(f"[favoritos] {cambios} cambios aplicados")
        escribir(FAVORITOS, favs)
    return favs, cambios > 0


def normal(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def coincide_palabra(o, palabras):
    texto = normal(f"{o['n']} {o['m']}")
    return [k for k in palabras if all(w in texto for w in normal(k).split())]


def avisar_favoritos(ofertas, favs, estado):
    avisados = estado.setdefault("avisados", {})  # "codigo|promo" -> fecha fin
    ahora = datetime.now(timezone.utc).isoformat()
    for k in [k for k, fin in avisados.items() if fin and fin < ahora]:
        del avisados[k]
    nuevos = []
    for o in ofertas:
        motivo = None
        if o["c"] in favs["productos"]:
            motivo = "⭐ favorito"
        else:
            kws = coincide_palabra(o, favs["palabras"])
            if kws:
                motivo = f"🔎 «{kws[0]}»"
        if not motivo:
            continue
        clave = f"{o['c']}|{o['pid']}"
        if clave in avisados:
            continue
        avisados[clave] = o["fin"] or ""
        nuevos.append((motivo, o))
    nuevos.sort(key=lambda x: (x[0] != "⭐ favorito", -x[1]["d"]))
    # Los favoritos van uno a uno, con foto. Las palabras clave, agrupadas.
    estrella = [o for m, o in nuevos if m.startswith("⭐")]
    palabra = [(m, o) for m, o in nuevos if not m.startswith("⭐")]
    for o in estrella[:15]:
        ntfy(f"⭐ {o['n'][:60]} en oferta",
             f"**{o['txt']}** → {euros(o['ef'])}/ud (antes {euros(o['p'])}, -{o['d']}%)"
             + (f"\nComprando {o['uds']}" if o["uds"] > 1 else "")
             + f"\nHasta el {dia(o['fin'])}" + (" · solo online" if o["online"] else ""),
             tags="star", prioridad=4, click=f"{PANEL_URL}#p={o['c']}", foto=o["imgL"] or o["img"])
    if len(estrella) > 15:
        ntfy(f"⭐ {len(estrella) - 15} favoritos más en oferta", "Ábrelos en el panel",
             tags="star", click=f"{PANEL_URL}#favoritos")
    if palabra:
        lineas = [f"{m} {o['n'][:45]}: {o['txt']} → {euros(o['ef'])}" for m, o in palabra[:12]]
        if len(palabra) > 12:
            lineas.append(f"… y {len(palabra) - 12} más")
        ntfy(f"🔎 {len(palabra)} ofertas de lo que vigilas", "\n".join(lineas), tags="mag",
             click=f"{PANEL_URL}#favoritos", foto=palabra[0][1]["img"])
    return len(estrella), len(palabra)


def euros(x):
    return f"{x:.2f} €".replace(".", ",")


def dia(iso):
    if not iso:
        return "?"
    d = datetime.fromisoformat(iso).astimezone(BRU)
    return ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][d.weekday()] + d.strftime(" %d/%m")


# ---------------- HISTORIAL ----------------
def actualizar_historial(ofertas):
    """historial[codigo] = [[fecha, precio_normal, precio_efectivo, promo], ...] (una entrada por promo)"""
    h = leer(HISTORIAL, {})
    hoy = datetime.now().strftime("%Y-%m-%d")
    for o in ofertas:
        filas = h.setdefault(o["c"], [])
        if not filas or filas[-1][3] != o["txt"] or filas[-1][2] != o["ef"]:
            filas.append([hoy, o["p"], o["ef"], o["txt"]])
    limite = (datetime.now() - timedelta(days=DIAS_HISTORIAL)).strftime("%Y-%m-%d")
    for c in list(h):
        h[c] = [f for f in h[c] if f[0] >= limite][-30:]
        if not h[c]:
            del h[c]
    escribir(HISTORIAL, h, compacto=True)
    return h


def main():
    forzar = "--forzar" in sys.argv
    estado = leer(ESTADO, {})
    favs, cambiaron = sincronizar_favoritos(estado)

    ultima = estado.get("ultima_descarga")
    ahora = datetime.now(BRU)
    toca = forzar or not ultima or (
        datetime.fromisoformat(ultima).astimezone(BRU).date() != ahora.date() and ahora.hour >= HORA_DESCARGA)

    if toca:
        brutos = descargar_todo()
        ofertas = [o for o in (simplificar(p) for p in brutos) if o]
        if len(ofertas) < 50:
            raise RuntimeError(f"Solo {len(ofertas)} ofertas: algo ha cambiado en la web de Delhaize")
        historial = actualizar_historial(ofertas)
        for o in ofertas:  # ¿mejor precio que las últimas veces?
            previos = [f[2] for f in historial.get(o["c"], [])[:-1]]
            o["min"] = min(previos) if previos else None
            o["veces"] = len(historial.get(o["c"], []))
        ids = sorted({o["pid"] for o in ofertas if o["pid"]})
        anteriores = set(estado.get("promos_ids", []))
        nuevas = [i for i in ids if i not in anteriores]
        semana_nueva = len(nuevas) > max(80, 0.25 * len(ids))
        datos = {"actualizado": datetime.now(timezone.utc).isoformat(), "total": len(ofertas),
                 "nuevas_ids": nuevas if anteriores else [], "ofertas": ofertas}
        escribir(OFERTAS, datos, compacto=True)
        estado["promos_ids"] = ids
        estado["ultima_descarga"] = datos["actualizado"]
        log(f"{len(ofertas)} ofertas guardadas ({len(nuevas)} promos nuevas)")
    else:
        datos = leer(OFERTAS, {"ofertas": []})
        ofertas = datos["ofertas"]
        semana_nueva = False
        if not cambiaron:
            log("Nada que hacer (descarga reciente, sin cambios de favoritos)")
            escribir(ESTADO, estado)
            return

    n_fav, n_kw = avisar_favoritos(ofertas, favs, estado)

    if semana_nueva:
        top = sorted([o for o in ofertas if not o["online"]], key=lambda o: (-o["d"], -o["top"]))[:5]
        ntfy(f"🛒 Ofertas nuevas en Delhaize: {len(ofertas)}",
             (f"{n_fav} favoritos y {n_kw} de tus búsquedas en oferta.\n" if n_fav or n_kw else "")
             + "Top descuentos:\n" + "\n".join(f"• {o['n'][:40]} {o['txt']}" for o in top),
             tags="shopping_cart,tada", prioridad=4, foto=top[0]["imgL"] if top else None)

    escribir(ESTADO, estado)


if __name__ == "__main__":
    main()
