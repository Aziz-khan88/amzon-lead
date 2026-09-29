import os
import sys
import django

# Configure Django settings
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

from leadfinder.models import Book, ResearchRun, Lead
from leadfinder.utils.normalize import normalized_book_key
from leadfinder.services.pipeline.process_book import process_book
from leadfinder.services.export.csv_export import export_leads_to_file

# The 100 books provided by the user
books_data = [
    {"isbn": "9781684363803", "title": "How to Teach Your Monster the ABCs"},
    {"isbn": "9781684364596", "title": "Just Like Rabbit"},
    {"isbn": "9798217118939", "title": "The Beatles: Baby Edition"},
    {"isbn": "9798217120499", "title": "The Cat in the Hat’s Super-Dee-Dooper Seek and Find!"},
    {"isbn": "9798217032464", "title": "Best Bunny Brother Ever"},
    {"isbn": "9781536250572", "title": "Bink and Gollie Three in One"},
    {"isbn": "9780823461141", "title": "Bored"},
    {"isbn": "9781536238198", "title": "Bunny and Clyde"},
    {"isbn": "9781665939409", "title": "Do I Love You? Yes I Do!"},
    {"isbn": "9798217223305", "title": "Dolly Parton Ultimate Fan Edition Little Golden Book Biography"},
    {"isbn": "9780063449510", "title": "The Goodnight Train Baby on Board"},
    {"isbn": "9781665938105", "title": "Hairstory"},
    {"isbn": "9780593905890", "title": "I Am the Birthday Bird"},
    {"isbn": "9781646145805", "title": "I Am the River"},
    {"isbn": "9780823462421", "title": "I Would Love You Still"},
    {"isbn": "9798217117642", "title": "If It Were My Birthday Party—By the Cat in the Hat"},
    {"isbn": "9781419779480", "title": "Little Bunny’s To-Do List"},
    {"isbn": "9781632176158", "title": "Love Like River and Sky"},
    {"isbn": "9780593646274", "title": "Momo Sees the Sea"},
    {"isbn": "9781547617913", "title": "More Than a Million"},
    {"isbn": "9781636551685", "title": "The Most Wonderful Gift in the World"},
    {"isbn": "9781536244328", "title": "Out and About in 100 Words"},
    {"isbn": "9780593814543", "title": "Pizza and Taco: Go Viral!"},
    {"isbn": "9798217025459", "title": "Prince: A Little Golden Book Biography"},
    {"isbn": "9781664300927", "title": "Rock and Roll"},
    {"isbn": "9798217023776", "title": "A Sea Monster Conundrum"},
    {"isbn": "9780593807286", "title": "Sweet Valley Twins: Three’s a Crowd"},
    {"isbn": "9798217118922", "title": "Taylor Swift: Baby Edition"},
    {"isbn": "9798225038083", "title": "There Was an Old Lady Who Swallowed a Clover!"},
    {"isbn": "9781338879186", "title": "Thick as Thieves"},
    {"isbn": "9781536248166", "title": "Unicornia: The Frozen Palace"},
    {"isbn": "9798217023981", "title": "The Wildest Thing"},
    {"isbn": "9781250386366", "title": "You Are a Diamond"},
    {"isbn": "9781536248227", "title": "Your Truck"},
    {"isbn": "9781536250633", "title": "Tu camioneta"},
    {"isbn": "9798888592366", "title": "Zamzam for Everyone"},
    {"isbn": "9780316209403", "title": "Basket Ball"},
    {"isbn": "9781419768866", "title": "Clothes to Make You Smile"},
    {"isbn": "9780062957061", "title": "Foote Was First!"},
    {"isbn": "9781547611676", "title": "Frog: A Story of Life on Earth"},
    {"isbn": "9780063317925", "title": "Girl Scouts: The Amazing Daisies Hunt for Colors"},
    {"isbn": "9780063254930", "title": "Gumshoe"},
    {"isbn": "9798889831587", "title": "I Love My People"},
    {"isbn": "9780374391942", "title": "If Animals Said I Love You, Mama"},
    {"isbn": "9781836007500", "title": "Oprah Winfrey"},
    {"isbn": "9781250364814", "title": "Unfunny Bunny"},
    {"isbn": "9780063483033", "title": "Bunny in Disguise"},
    {"isbn": "9781665990646", "title": "Chicka Chicka Peep Peep"},
    {"isbn": "9781665988995", "title": "Could That Be the Easter Bunny?"},
    {"isbn": "9781536243949", "title": "Fairy Door Diaries: Eliza and the Flower Fairies"},
    {"isbn": "9781665980104", "title": "It’s Almost Time for … Easter!"},
    {"isbn": "9780063327054", "title": "Melodies of the Weary Blues"},
    {"isbn": "9798347100767", "title": "My Heart Knows Love"},
    {"isbn": "9781665988889", "title": "My Little Chick"},
    {"isbn": "9781665988865", "title": "Old MacDonald’s Easter Farm"},
    {"isbn": "9781681198187", "title": "Troubled Waters"},
    {"isbn": "9781665951050", "title": "Welcome, Spring!"},
    {"isbn": "9781250851970", "title": "Wrong Friend"},
    {"isbn": "9780063389083", "title": "Cool Buds: Treasure Map!"},
    {"isbn": "9798217029167", "title": "Crouton: One Cat’s Adoption Tale"},
    {"isbn": "9781837291243", "title": "Formula Fast"},
    {"isbn": "9798347110230", "title": "I’ve Got a Dog!"},
    {"isbn": "9780063216716", "title": "Mungo on His Own"},
    {"isbn": "9798217115921", "title": "Richard Scarry’s Easter Cars and Trucks"},
    {"isbn": "9780063264755", "title": "Stronger Than"},
    {"isbn": "9798985849455", "title": "Together, Right Now"},
    {"isbn": "9781592704774", "title": "What a Small Cat Needs"},
    {"isbn": "9780063354296", "title": "Zeb and Bel: A Case of Bird Problems"},
    {"isbn": "9798217120475", "title": "123s of Kindness at Bedtime"},
    {"isbn": "9781836008774", "title": "America the Beautiful"},
    {"isbn": "9798887772370", "title": "Animal Actions: Buzz Like a Bee"},
    {"isbn": "9780593707401", "title": "Because of a Shoe"},
    {"isbn": "9783039640898", "title": "The Big Book of Pi"},
    {"isbn": "9781546171737", "title": "A Blood Moon"},
    {"isbn": "9781250906885", "title": "Bread Is Love"},
    {"isbn": "9781536251784", "title": "Bunny and Clyde on the Lam"},
    {"isbn": "9781547609413", "title": "Camp Monster"},
    {"isbn": "9781835691540", "title": "Can Crabs and Crustaceans Survive Anywhere?"},
    {"isbn": "9781836008606", "title": "The Chase"},
    {"isbn": "9781546183020", "title": "The Day the Mac ’n’ Cheese Ran Out"},
    {"isbn": "9780063460775", "title": "Decoy Saves Opening Day"},
    {"isbn": "9781838742973", "title": "Detective Stanley and the Green Thumbed Thief"},
    {"isbn": "9781761602535", "title": "Diary of a Marine Biologist"},
    {"isbn": "9783039641017", "title": "Faster Than a Jet, Bigger Than a Whale"},
    {"isbn": "9780593305300", "title": "Hilo Presents: The Mighty"},
    {"isbn": "9781836008057", "title": "Holi"},
    {"isbn": "9798888598962", "title": "Home Away from Home"},
    {"isbn": "9798765619858", "title": "A Home on the Page"},
    {"isbn": "9781546137719", "title": "I Survived the California Wildfires, 2018"},
    {"isbn": "9798217026029", "title": "I’m So Happy You’re Here"},
    {"isbn": "9780063354104", "title": "A Kid Like Me"},
    {"isbn": "9781464239410", "title": "Leaf Thief: 1, 2, 3, Can You Count Along?"},
    {"isbn": "9781250392817", "title": "The Lions’ Run"},
    {"isbn": "9780316561341", "title": "Maya’s Big Question"},
    {"isbn": "9780316442169", "title": "The Mighty Macy"},
    {"isbn": "9781664300804", "title": "Mister Norton’s New Truck"},
    {"isbn": "9781464268854", "title": "The Princess and the Unicorn"},
    {"isbn": "9781536247978", "title": "Relic Hamilton, Genie Hunter"},
    {"isbn": "9781338673852", "title": "Rumpelstiltskin"},
    {"isbn": "9781250782793", "title": "Space Chasers: To the Moon"}
]

def main():
    print("Initializing User ISBN Batch Run...")
    run, created = ResearchRun.objects.get_or_create(
        keyword="User Request: 100 ISBNs",
        defaults={
            "source_provider": "manual",
            "max_books": len(books_data),
            "settings_json": {
                "require_amazon_url": True,
                "require_public_email": False,
                "include_social_only_leads": True,
                "run_video_search": True,
                "run_groq_ai_extraction": True,
            }
        }
    )
    
    if created:
        print(f"Created new ResearchRun with ID: {run.id}")
        for idx, book_item in enumerate(books_data, 1):
            code = book_item["isbn"]
            title = book_item["title"]
            Book.objects.create(
                research_run=run,
                title=title,
                asin=code,
                amazon_book_url=f"https://www.amazon.com/dp/{code}",
                amazon_source_url=f"https://www.amazon.com/dp/{code}",
                normalized_key=normalized_book_key(title, "", code),
                source_provider="manual",
                source_raw_json={"processing_status": "pending"},
            )
        print(f"Created Book records for all {len(books_data)} books.")
    else:
        print(f"Resuming existing ResearchRun with ID: {run.id}")

    run.mark_running()
    
    books = list(run.books.all())
    total = len(books)
    print(f"Total books to process: {total}")
    
    completed_count = 0
    skipped_count = 0
    failed_count = 0
    
    for i, book in enumerate(books, 1):
        raw = book.source_raw_json or {}
        status = raw.get("processing_status", "pending")
        if status == "completed":
            print(f"[{i}/{total}] Skipping completed book: '{book.title}' (ISBN: {book.asin})")
            skipped_count += 1
            continue
            
        print(f"\n[{i}/{total}] Processing: '{book.title}' (ISBN: {book.asin})")
        # Update processing status
        raw["processing_status"] = "processing"
        book.source_raw_json = raw
        book.save(update_fields=["source_raw_json", "updated_at"])
        
        try:
            process_book(
                book,
                run_video_search=True,
                run_ai_extraction=True
            )
            book.refresh_from_db()
            raw = book.source_raw_json or {}
            raw["processing_status"] = "completed"
            book.source_raw_json = raw
            book.save(update_fields=["source_raw_json", "updated_at"])
            
            lead = Lead.objects.filter(book=book).first()
            if lead:
                print(f"       -> Done! Lead Tier: {lead.lead_tier}, Score: {lead.lead_score}, Contact: {lead.public_email or lead.public_phone or 'None'}")
            else:
                print("       -> Done! (No Lead generated)")
            completed_count += 1
        except Exception as exc:
            import traceback
            traceback.print_exc()
            raw = book.source_raw_json or {}
            raw["processing_status"] = "failed"
            raw["error_message"] = str(exc)
            book.source_raw_json = raw
            book.save(update_fields=["source_raw_json", "updated_at"])
            print(f"       -> Failed! Error: {exc}")
            failed_count += 1
            
    run.mark_completed()
    print("\n" + "="*50)
    print("ResearchRun Complete!")
    print(f"Processed: {completed_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Failed: {failed_count}")
    
    # Export results
    output_csv = "data/user_isbn_leads.csv"
    leads_qs = Lead.objects.filter(book__research_run=run).order_by("-lead_score", "-created_at")
    exported = export_leads_to_file(leads_qs, output_csv)
    print(f"Exported {exported} leads to {output_csv}")
    print("="*50)

if __name__ == "__main__":
    main()
