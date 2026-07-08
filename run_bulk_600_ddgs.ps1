$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Ali.Raza\Desktop\lead-scraping\django\booktrailer_leads"

& "C:\Users\Ali.Raza\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" manage.py run_bulk_lead_research `
  --target-leads 600 `
  --batch-size 50 `
  --provider ddgs `
  --no-video-search `
  --include-existing `
  --allow-missing-email `
  --allow-missing-phone `
  --max-batches 80 `
  --output "data\book_trailer_leads_600_latest_amazon.csv" `
  --keyword "children's book" `
  --keyword "children picture book" `
  --keyword "kids picture book" `
  --keyword "bedtime children's book" `
  --keyword "children book illustration" `
  --keyword "self published children's book" `
  --keyword "independent children's author" `
  --keyword "new children picture book" `
  --keyword "latest children's book" `
  --keyword "children paperback picture book"
