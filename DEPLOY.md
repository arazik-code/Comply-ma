# COMPLY-MA — Guide de Déploiement Production

Outil de **structuration et d'archivage** de la facturation électronique marocaine.
Ne constitue pas un conseil comptable ou fiscal. Validation par un expert-comptable requise.

---

## 1. Prérequis

- Docker + Docker Compose (v2)
- 2 Go de RAM minimum, port 8000 disponible
- Un certificat PKCS#12 de signature (Barid e-Sign ou CA marocain) — production
- Un reverse proxy TLS (nginx, Caddy, Traefik) devant l'application — l'app écoute en HTTP

## 2. Configuration

```bash
cp .env.example .env
```

Remplir **obligatoirement** :

| Variable | Description |
|---|---|
| `COMPLY_MA_ENVIRONMENT` | `production` (l'app refuse de démarrer avec la clé par défaut sinon) |
| `COMPLY_MA_SECRET_KEY` | Clé de sessions — `python -c "import secrets; print(secrets.token_urlsafe(48))"` |

Principales variables optionnelles :

| Variable | Défaut | Rôle |
|---|---|---|
| `COMPLY_MA_HTTPS_ONLY` | `false` | Flag `Secure` sur les cookies (mettre `true` derrière TLS) |
| `COMPLY_MA_CLEARANCE_PROVIDER` | `mock` | `mock` = dev/test ; `dgi` = API réelle (quand publiée) |
| `COMPLY_MA_PKCS12_CERT_PATH` | — | Certificat de signature production (sinon auto-signé + avertissement) |
| `COMPLY_MA_SMTP_*` | — | Envoi des factures par email |
| `COMPLY_MA_WHATSAPP_*` | — | Bridge WhatsApp (optionnel) |
| `COMPLY_MA_LOG_FORMAT` | `text` | `json` recommandé en production (collecte de logs) |
| `COMPLY_MA_RETENTION_YEARS` | `10` | Rétention légale des archives |

### Sécurité intégrée

- **CSRF** : token de session vérifié sur toutes les requêtes POST/PUT/PATCH/DELETE
- **Rate limiting login** : 10 échecs / 5 min par IP → verrouillage 15 min
- **En-têtes de sécurité** : CSP, X-Frame-Options DENY, nosniff, etc.
- **Uploads** : logos limités à PNG/JPEG/WebP, 2 Mo max, magic bytes vérifiés
- **XML** : parsing durci anti-XXE sur les factures fournisseurs importées
- **Démarrage** : refus en production si `SECRET_KEY` par défaut ou `DEBUG=true`

## 3. Démarrage

### Mode Cabinet (fiduciaire, multi-clients)

```bash
cd deploy
docker compose -f docker-compose.cabinet.yml up -d --build
```

### Mode Simple (une entreprise)

```bash
cd deploy
docker compose -f docker-compose.single.yml up -d --build
```

Le conteneur expose `/health` (utilisé par le Docker healthcheck).

## 4. Première mise en service (checklist)

1. **Créer le compte administrateur** — au premier démarrage, la base est vide ;
   passer par l'écran de configuration `/setup` après le premier login.
   Le mode cabinet demande de créer le cabinet via `/cabinet` (formulaire de setup).
2. **Changer immédiatement le mot de passe par défaut** (`admin`/`admin123` en mode démo —
   ne jamais garder en production).
3. **Installer le certificat PKCS#12** : monter le fichier `.p12` et renseigner
   `COMPLY_MA_PKCS12_CERT_PATH` + `COMPLY_MA_PKCS12_PASSPHRASE`.
   Sans cela, la signature XML utilise un certificat auto-signé (avertissement au démarrage).
4. **Configurer le SMTP** et tester l'envoi d'une facture par email.
5. **Vérifier** `curl http://localhost:8000/health` → `{"status": "ok", ...}`
6. **Placer le reverse proxy TLS** devant le port 8000 et passer `COMPLY_MA_HTTPS_ONLY=true`.

### Seed cabinet (démo uniquement)

```bash
docker exec -it comply-ma-cabinet python seed_cabinet.py
# Login démo : admin / admin123 — À NE JAMAIS UTILISER EN PRODUCTION
```

## 5. Structure des données (volume `comply-data`)

```
data/
  cabinets/
    metadata.db          ← Base cabinet (utilisateurs, registre clients)
    {cabinet_id}/
      clients/
        {client_id}.db   ← Base isolée de chaque client
  archives/              ← Archives ZIP (rétention légale 10 ans)
  reports/               ← Rapports de conformité générés
  logos/                 ← Logos des entreprises
  certs/                 ← Certificats de signature
  comply-ma.log          ← Logs applicatifs (rotation 10 Mo × 5)
```

## 6. Sauvegarde & restauration

### Sauvegarde (à automatiser — exemple cron quotidien)

```bash
# Arrêter l'écriture le temps de la copie cohérente :
docker stop comply-ma-cabinet
docker run --rm -v comply-ma_comply-data:/data -v "$PWD/backups:/backup" \
  alpine tar czf /backup/comply-$(date +%F).tar.gz -C /data .
docker start comply-ma-cabinet

# Conserver 30 jours :
find backups/ -name "comply-*.tar.gz" -mtime +30 -delete
```

> SQLite supporte aussi la sauvegarde à chaud via `sqlite3 .backup`, mais
> l'arrêt bref du conteneur garantit la cohérence de toutes les bases clients.

### Restauration

```bash
docker stop comply-ma-cabinet
docker run --rm -v comply-ma_comply-data:/data -v "$PWD/backups:/backup" \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/comply-YYYY-MM-DD.tar.gz -C /data"
docker start comply-ma-cabinet
```

### Vérification post-restauration

```bash
curl http://localhost:8000/health
docker logs comply-ma-cabinet --tail 50
# Puis : login, vérifier la liste des clients cabinet et une facture récente.
```

## 7. Mise à jour

```bash
cd deploy
git pull
docker compose -f docker-compose.cabinet.yml up -d --build
# Le schéma SQLite est créé par create_all au démarrage ; vérifier les logs
# pour toute erreur de migration et tester /health.
```

### Rollback

```bash
git checkout <tag-ou-commit-précédent>
docker compose -f docker-compose.cabinet.yml up -d --build
# Si besoin, restaurer la sauvegarde de la veille (section 6).
```

## 8. Surveillance & dépannage

| Symptôme | Action |
|---|---|
| L'app refuse de démarrer (`SECRET_KEY`) | Renseigner `COMPLY_MA_SECRET_KEY` dans `.env` |
| `clearance_provider_is_mock` dans les logs | Comportement attendu tant que l'API DGI n'est pas publiée |
| `xml_signing_self_signed` | Installer le certificat PKCS#12 de production |
| 429 sur /login | Trop de tentatives — verrouillage 15 min par IP |
| `client_db_open_failed` | Base client manquante — recréer le client ou restaurer un backup |
| `retention_enforcement_failed` | Vérifier les permissions sur `data/archives/` |

Logs : `docker logs -f comply-ma-cabinet` et `data/comply-ma.log`.

## 9. Limitations connues (transparence)

- **Clearance DGI** : l'API DGI n'est pas encore publiée ; en mode `mock`, les factures
  sont marquées « cleared » **sans transmission réelle**. Un avertissement est émis au
  démarrage en production. Basculer sur `dgi` dès que l'API est disponible.
- **MOWAKABA** : éligibilité auto-entrepreneur NON vérifiée — confirmer avec Maroc PME.
- **Avertissement légal** : outil de structuration et d'archivage — la validation par un
  expert-comptable reste requise.
