from apps.marketplace.models import SubOrder
from apps.marketplace.services.wallet_service import release_to_available
subs = SubOrder.objects.filter(status='CONFIRMED')
print('CONFIRMED count:', subs.count())
for sub in subs:
    result = release_to_available(sub)
    print('SubOrder', sub.pk, result)
