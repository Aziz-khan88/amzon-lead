$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Ali.Raza\Desktop\lead-scraping\django\booktrailer_leads"

& "C:\Users\Ali.Raza\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" manage.py run_bulk_lead_research `
  --target-leads 600 `
  --batch-size 50 `
  --provider tavily `
  --no-video-search `
  --include-existing `
  --allow-missing-email `
  --allow-missing-phone `
  --max-batches 80 `
  --output "data\book_trailer_leads_600_latest_amazon.csv" `
  --keyword "children's book 2026 new release" `
  --keyword "children's book 2025 new release" `
  --keyword "new children picture book 2026 author" `
  --keyword "new children picture book 2025 author" `
  --keyword "latest children's book author" `
  --keyword "children picture book paperback author" `
  --keyword "kids picture book new release author" `
  --keyword "bedtime children's book author" `
  --keyword "self published children's book author" `
  --keyword "independent children's author picture book"
