from telethon.sync import TelegramClient
import csv

api_id = 20133532
api_hash = "9c0cfd8f61aa9127dc551839375f095c"
phone = "+919149076448"
group_link = "https://t.me/+z75YmMh60pkxMzdl"  # public group OR private group with username

all_participants = []
unique_ids = set()

with TelegramClient('session_user', api_id, api_hash) as client:
    group_entity = client.get_entity(group_link)

    # iter_participants automatically handles pagination
    for p in client.iter_participants(group_entity, aggressive=True):
        if p.id not in unique_ids:
            unique_ids.add(p.id)
            all_participants.append({
                "id": p.id,
                "username": getattr(p, "username", ""),
                "first_name": getattr(p, "first_name", ""),
                "last_name": getattr(p, "last_name", ""),
                "phone": getattr(p, "phone", "")
            })
        print(f"Fetched {len(all_participants)} participants...", end='\r')

# --- Save to CSV ---
with open("members.csv", "w", newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=["id", "username", "first_name", "last_name", "phone"])
    writer.writeheader()
    writer.writerows(all_participants)

print(f"\nTotal unique members fetched: {len(all_participants)}")
