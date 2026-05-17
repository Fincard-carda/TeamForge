# TeamForge Coding Standards (v0.1)

> Bu dokuminstant sahibi: **Tech Lead**. All dev'ler bu standartlara uyar.
> TL bu fileyi `knowledge.write_spec("coding-standards-v1", ...)` ile genisletir.

## Genel prensipler

1. **Readability over cleverness** — anlasilmasi 30 saniyenin uzerinde sure alan kod parcasi gozden gecirilir
2. **Hexagonal architecture** — domain, application, infrastructure ayri katmanlarda
3. **Hassas veri limitlari** — Domain-spesifik PII/secret veriler (kart, saglik, kimlik) ASLA log/memory/disk�a yazilmaz, only tokenized/hashed tutulur. Compliance kalemleri config/tech_stack.yaml uzerinden tanimlanir.
4. **Idempotency** — her writing endpoint'i Idempotency-Key destaddr
5. **Test pyramid** — unit > integration > e2e oranlari korunur

## Java / Kotlin (backend)
- **Format:** spotless plugin, google-java-format / ktlint kurali
- **Naming:** PascalCase class, camelCase metod, UPPER_SNAKE constants
- **Exception:** sealed type hierarchy ile domain errorlari, `RuntimeException` direkt kullanilmaz
- **Logging:** SLF4J + structured (key=value); PAN, CVV, password ASLA log'a
- **Testcontainers** entegrasyon test for zorunlu (Postgres, Redis, Kafka)
- **Coverage hedef:** %80 line coverage; kritik domain for %90

## Swift (iOS)
- **Format:** swift-format default + Apple guidelines
- **Concurrency:** `actor` paylasilan state for, `async/await` callback'ler instead of
- **Optionals:** `!` (force unwrap) PR'da reddedilir; `guard let` veya `if let`
- **Tests:** XCTest + XCTestPlan ile env bazli
- **Secure Enclave** sensitif veri for

## Kotlin (Android)
- **Format:** ktlint + detekt
- **Coroutines:** `runBlocking` test outside forbidden
- **Hilt** DI, manuel singleton forbidden
- **Compose:** stable + immutable annotation'lari sik usage
- **Tests:** Espresso UI, MockK

## TypeScript / React (frontend)
- **Format:** Prettier + ESLint (recommended + react-hooks)
- **Strict mode:** `tsconfig.strict: true`, `noImplicitAny: true`
- **Components:** Server Component before, client component only etkilesim for (Next.js 14)
- **State:** TanStack Query server state, Zustand client; Redux forbidden (overkill)
- **Forms:** react-hook-form + zod, browser validation alone sufficient not

## Terraform (DevOps)
- **Format:** `terraform fmt`, `tflint`
- **Modul structurei:** `modules/<name>/{main,variables,outputs,versions}.tf`
- **State:** S3 backend + DynamoDB lock
- **No hard-coded values** — variable + tfvars
- **Plan-before-apply** always; `terraform apply --auto-approve` PR'da forbidden

## Common — security must-haves
- Secret never repo'ya commit edilmez (gitleaks pre-commit hook)
- Dependency vuln scan: Dependabot + Snyk
- SAST: SonarQube quality gate
- Container scan: Trivy
- Mutual TLS service mesh forde

## PR / artifact teslim formati (worker -> TL)
- Modul/file agaci list
- Yeni dependency'ler (varsa version + sebep)
- Test coverage delta
- Breaking change var mi?
- Known limitations / TODO

## Review verdict kriterleri (TL bunlara bakar)

### review_passed
- Coding standards uyumu var
- Acceptance criteria karsilanmis
- Test coverage kabul edilebilir
- Security/PCI flag none
- Performance hedefleri mantikli

### needs_changes
- Yukaridakilerden 1-2 madde eksik
- Mantikli efor ile fixilebilir

### rejected
- Mimari yaklasim yanlis
- Mevcut sheremle entegrasyon kirilmis
- Major refactor required — BA again plan yapmali
