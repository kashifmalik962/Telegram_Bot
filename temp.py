import pandas as pd

# Load your CSV file
df = pd.read_csv("Telegram_DB.import_users.csv")

# Filter rows where telegram_id is empty, NaN, or blank string
filtered_df = df[(df["telegram_id"].isna()) | (df["telegram_id"] == "")]

# Save to a new CSV
filtered_df.to_csv("empty_telegram_id.csv", index=False)

print("Filtered rows saved in empty_telegram_id.csv")
