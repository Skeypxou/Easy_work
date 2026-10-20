# Atelier PVC Pro — logiciel de devis

Application Streamlit pour gérer les clients, un catalogue d'articles et les devis PDF. Elle comprend un tableau de bord, la gestion des clients, un catalogue, la création de devis avec plusieurs lignes, remises, TVA configurable, historique, statuts et export PDF/CSV.

## Fichiers

- `app.py` : application complète. Les fonctions de base de données et le PDF sont dans ce même fichier pour éviter les erreurs d'import de modules internes.
- `requirements.txt` : dépendances à installer.
- `.gitignore` : empêche l'ajout de fichiers temporaires et de la base de données locale au dépôt.

## Lancer localement

```bash
python -m venv .venv
# Windows PowerShell : .\.venv\Scripts\Activate.ps1
# macOS/Linux : source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

La base SQLite est créée automatiquement dans `data/atelier.db`.

## Déployer sur Streamlit Community Cloud

1. Envoyer `app.py`, `requirements.txt`, `README.md` et `.gitignore` à la racine d'un dépôt GitHub.
2. Sur Streamlit Community Cloud, créer une application à partir de ce dépôt.
3. Choisir la branche `main` et le fichier principal `app.py`.
4. Déployer. Streamlit installe les dépendances depuis `requirements.txt`.

## Important sur les données

SQLite est pratique pour tester l'application et l'utiliser localement. Le système de fichiers d'une application Streamlit Cloud n'est pas un stockage durable garanti. Pour une utilisation réelle en ligne, connecter une base PostgreSQL hébergée (par exemple Supabase) avant de saisir des données importantes. Ne jamais déposer `data/atelier.db` ni des secrets dans GitHub.

La TVA par défaut est un paramètre modifiable : vérifiez le taux qui s'applique à votre entreprise avant d'émettre de vrais devis. Les calculs de menuiserie et les listes de coupe propres à chaque fabricant de profils ne sont pas encore inclus dans cette version axée sur les devis commerciaux.
