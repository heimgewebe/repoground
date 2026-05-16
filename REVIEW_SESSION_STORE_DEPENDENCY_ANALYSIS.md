# Review: Session Persistence via DbSessionStore – Dependency Graph Verification

## These / Antithese / Synthese

**These:** Der wichtigste Rework ist erledigt: Die DB-Integrationstests führen jetzt selbst Migrationen aus. Damit ist der Proof nicht mehr abhängig von einer schon „magisch" vorbereiteten Datenbank.

**Antithese:** Der `Cargo.lock`-Beifang bleibt ungeklärt. `sqlx-mysql`, `sqlx-sqlite`, `libsqlite3-sys`, `rsa` usw. sind weiterhin im Diff. Das kann durch `sqlx`/`migrate` legitim sein, ist aber ohne `cargo tree -i ...` noch nicht bewiesen.

**Synthese:** Der PR ist deutlich besser, aber noch **nicht final freizugeben**, solange der Dependency-Graph nicht belegt ist. Die Datenbankseite ist jetzt ordentlich; die Abhängigkeitsseite hat noch Nebel. Und Nebel in `Cargo.lock` ist wie Nebel im Maschinenraum: romantisch nur für Leute, die nicht deployen müssen.

---

## Befund zum neuen Diff

### Erledigt

**1. Tests sind jetzt migrationsrobust**

Neu:

```rust
async fn ensure_migrations(pool: &sqlx::PgPool) {
    let migrations_dir: PathBuf = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("migrations");

    let migrator = sqlx::migrate::Migrator::new(migrations_dir)
        .await
        .expect("failed to load migrations");

    migrator.run(pool).await.expect("failed to run migrations");
}
```

Und in `connect_pool()`:

```rust
ensure_migrations(&pool).await;
```

Das löst den vorherigen Blocker.

**2. Startup-Migration nutzt stabilen Pfad**

In `lib.rs`:

```rust
let migrations_dir: PathBuf = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("migrations");
```

Das ist besser als `./migrations`, weil es nicht vom aktuellen Arbeitsverzeichnis abhängt.

**3. `touch()`-SQL ist bereinigt**

Die Einrückung ist jetzt sauber:

```rust
WHERE id = $1
  AND expires_at > NOW()
  AND last_active < NOW() - INTERVAL '5 minutes'
```

Gut.

---

## Noch offen: Dependency-Beifang

Der PR aktiviert:

```toml
sqlx = { version = "0.8.1", default-features = false, features = ["runtime-tokio", "postgres", "chrono", "migrate"] }
```

Trotz `default-features = false` erscheinen im Lockfile unter anderem:

```text
sqlx-mysql
sqlx-sqlite
libsqlite3-sys
rsa
sha1
num-bigint-dig
```

Das muss nicht falsch sein. Es kann durch `sqlx`-Feature-Verkettung entstehen. Aber es ist ein neuer transitive Dependency-Footprint im API-Pfad.

**X fehlt, nötig für Y:**
Es fehlen `cargo tree -i`-Belege, nötig für die Entscheidung, ob der Lockfile-Zuwachs akzeptierter Preis von `sqlx/migrate` ist oder unerwünschter Beifang.

---

## Empfehlung

Noch **nicht ready-for-review/merge**. Erst diesen Beweis nachliefern:

```bash
cargo tree -p weltgewebe-api -i sqlx-mysql || true
cargo tree -p weltgewebe-api -i sqlx-sqlite || true
cargo tree -p weltgewebe-api -i libsqlite3-sys || true
cargo tree -p weltgewebe-api -i rsa || true
cargo tree -p weltgewebe-api -i sqlx-macros || true
```

Dann gibt es zwei Pfade:

### Pfad A — Beifang ist durch `sqlx/migrate` unvermeidbar

Dann akzeptieren, aber PR-Beschreibung ergänzen:

```text
Note: Enabling sqlx/migrate for runtime startup migrations expands the transitive sqlx dependency graph and pulls additional sqlx backend crates into Cargo.lock. This is accepted for this PR because startup migrations are part of the Phase 5 target.
```

### Pfad B — Beifang ist vermeidbar

Dann reduzieren: entweder Feature-Kombination korrigieren oder Startup-Migration anders lösen.

---

## Alternative Sinnachse

Nicht nur fragen: „Wie bauen wir Startup-Migration sauber ein?"

Sondern auch: **Soll die API überhaupt Migrationen beim Start ausführen?**

Zwei legitime Modelle:

1. **API-owned migration:** App startet, migriert selbst, danach läuft sie. Vorteil: weniger Deployment-Schritte. Risiko: App-Start hängt stärker an DB-Rechten und Migrationszustand.

2. **Deploy-owned migration:** CI/Deploy führt `sqlx migrate run` aus, API erwartet fertige DB. Vorteil: schlanker Runtime-Footprint, weniger Rechte im laufenden Dienst. Risiko: mehr Betriebsdisziplin nötig.

Da eure Roadmap Startup-Migration verlangt, ist Pfad 1 aktuell konsistent. Aber der Lockfile-Beifang ist genau der Preis, den diese Entscheidung sichtbar macht.

---

## Risiko / Nutzen

**Nutzen:** Hoch. Session-Persistenz ist jetzt real implementiert, nicht nur bewiesen.

**Risiko:** Mittel. Runtime-Migrationen erhöhen Startabhängigkeit von PostgreSQL und erweitern vermutlich den Dependency-Footprint.

**Technisches Risiko:** Der große Lockfile-Zuwachs kann Security-/Build-/Audit-Fläche erhöhen. Nicht dramatisch, aber dokumentationspflichtig, falls unvermeidbar.

---

## Optimierungsgrad

**Was:** Session-Persistenz, Restart-Stabilität, Test-Reproduzierbarkeit.
**Wie:** `DbSessionStore`, Runtime-Migration, migrationsrobuste Integrationstests.
**Wodurch:** Session-State wird dauerhaft in PostgreSQL geschrieben und Tests bauen ihre DB-Voraussetzung selbst auf.
**Stärke:** Hoch, sobald Dependency-Beifang belegt ist.
**Nebenwirkung:** Mehr DB-Kopplung beim Start und größerer transitive Dependency-Graph.

---

## Essenz

**Hebel:** `cargo tree -i` für den Lockfile-Zuwachs.
**Entscheidung:** Noch nicht mergen, aber nahe dran.
**Nächste Aktion:** Dependency-Beweis liefern; danach wahrscheinlich ready.

---

## Agent-Anweisung

```
Bitte PR #1072 weiter prüfen, noch nicht ready-for-review setzen.

Aktueller Stand:
- DbSessionStore-Implementierung sieht strukturell gut aus.
- DB-Integrationstests sind jetzt migrationsrobust.
- Startup-Migration nutzt CARGO_MANIFEST_DIR/migrations.
- Vorheriger Test-Migrationsblocker ist erledigt.

Offen bleibt nur der Dependency-Graph.

Bitte ausführen und Output posten:

cargo tree -p weltgewebe-api -i sqlx-mysql || true
cargo tree -p weltgewebe-api -i sqlx-sqlite || true
cargo tree -p weltgewebe-api -i libsqlite3-sys || true
cargo tree -p weltgewebe-api -i rsa || true
cargo tree -p weltgewebe-api -i sqlx-macros || true

Wenn der Beifang eindeutig durch sqlx/migrate entsteht:
- PR-Beschreibung ergänzen: Runtime-Migration via sqlx/migrate erweitert den transitive Dependency-Footprint.
- Keine Codeänderung nötig.

Wenn der Beifang nicht notwendig ist:
- Cargo.toml/Cargo.lock bereinigen.
- Danach erneut validieren.

Pflicht-Proofs danach:
cargo fmt --all -- --check
cargo clippy -p weltgewebe-api --all-targets --all-features -- -D warnings
cargo test --locked -p weltgewebe-api
git diff --check

DB-Proof:
DATABASE_URL=postgres://...:5432/... cargo test --locked -p weltgewebe-api --test db_session_store_persistence -- --include-ignored

Stop-Regel:
Nicht mergen ohne cargo-tree-Beleg zum neuen sqlx-Dependency-Footprint.
```
