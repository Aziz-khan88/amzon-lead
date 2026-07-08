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
  --output "data\children_book_illustration_600_amazon_author.csv" `
  --keyword "children book illustration" `
  --keyword "children's book illustration" `
  --keyword "children picture book illustration" `
  --keyword "kids book illustration" `
  --keyword "illustrated children's book" `
  --keyword "children book illustrator author" `
  --keyword "picture book illustrator author" `
  --keyword "kids picture book illustration" `
  --keyword "children illustrated storybook" `
  --keyword "bedtime picture book illustration"
