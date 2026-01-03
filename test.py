
import os
from dotenv import load_dotenv; load_dotenv()
print(os.getenv("STRIPE_WEBHOOK_SECRET"))
