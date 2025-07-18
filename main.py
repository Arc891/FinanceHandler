import os
import dotenv
import gocardless_pro

if (not dotenv.load_dotenv()):
    raise Exception("Failed to load environment variables")

client = gocardless_pro.Client(
    # We recommend storing your access token in an
    # environment variable for security
    access_token=os.environ['GC_ACCESS_TOKEN'],
    # Change this to 'live' when you are ready to go live.
    environment='sandbox'
)

customers = client.customers.list().records
print(customers)
print([customer.email for customer in customers])