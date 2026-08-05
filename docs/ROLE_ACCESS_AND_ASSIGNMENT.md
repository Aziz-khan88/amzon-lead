# Role access and lead assignment

## Access model

| Role | Lead visibility | Research/import | Lead assignment | Team accounts |
| --- | --- | --- | --- | --- |
| Super admin | All leads | Full | Full | Create, disable, and change every role |
| Admin | All leads | Full | Full | Create and disable sales accounts |
| Salesperson | Current assigned leads only | No access | Update own task outcome | No access |

Every application data route requires login. Browser pages use an HTTP-only session cookie and CSRF protection. API clients obtain a short-lived JWT from `POST /api/auth/token/` and refresh it at `POST /api/auth/token/refresh/`. Tokens contain `role` and `name` claims. Anonymous API traffic is throttled, and browser login allows five failed attempts per IP/username in 15 minutes.

## First account

After migrations, create the first super administrator interactively:

```powershell
python manage.py bootstrap_superadmin --username lead-admin --email admin@example.com
```

The command prompts for the password and does not accept it as a command argument.

## Assignment flow

1. A Super Admin or Admin creates sales accounts on **Team**.
2. Leads can be selected and assigned or reassigned from the Leads table. Reassignment closes the previous current assignment and preserves its history.
3. An admin creates a daily schedule under **Lead assignment**, selecting the salesperson, weekdays, time, quota, contact requirements, verification requirement, and minimum score.
4. `python manage.py run_scheduler_loop --daemon` executes research hunts and lead-assignment schedules.
5. Allocation runs in a transaction, excludes do-not-contact and currently assigned leads, and prioritizes verification score then lead score. Empty pools record a successful run with zero assignments.
6. The salesperson records task status, contact quality, and notes. Terminal outcomes get completion timestamps; conversions also get a conversion timestamp.
7. Admin Dashboard and Team screens report assigned, pending, active, completed, converted, duplicate, and invalid-data work.

## Task outcomes

Task states are Pending, In progress, Contacted, Follow up, Completed, Converted, Not interested, No response, Invalid or fake data, and Duplicate. Contact quality can be Complete, Email only, Phone only, Missing, Fake/invalid, Wrong person, or Not checked.

## Production security

- Set `DEBUG=False`, a random `SECRET_KEY` of at least 32 characters, and explicit `ALLOWED_HOSTS`.
- HTTPS mode enables secure cookies, HSTS, SSL redirect, frame denial, content-type protection, and same-origin referrer policy.
- Run one managed scheduler worker. Transactions and the unique-current-assignment database constraint prevent duplicate ownership.
- Back up the database before role or assignment migrations.
