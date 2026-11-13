"""Stable Indian state/UT identifiers; unknown identifiers are never paired."""
import re
import unicodedata

NAMES={'AP':'Andhra Pradesh','AR':'Arunachal Pradesh','AS':'Assam','BR':'Bihar','CG':'Chhattisgarh','GA':'Goa','GJ':'Gujarat','HR':'Haryana','HP':'Himachal Pradesh','JH':'Jharkhand','KA':'Karnataka','KL':'Kerala','MP':'Madhya Pradesh','MH':'Maharashtra','MN':'Manipur','ML':'Meghalaya','MZ':'Mizoram','NL':'Nagaland','OD':'Odisha','PB':'Punjab','RJ':'Rajasthan','SK':'Sikkim','TN':'Tamil Nadu','TS':'Telangana','TR':'Tripura','UP':'Uttar Pradesh','UK':'Uttarakhand','WB':'West Bengal','AN':'Andaman and Nicobar Islands','CH':'Chandigarh','DN':'Dadra and Nagar Haveli and Daman and Diu','DL':'Delhi','JK':'Jammu and Kashmir','LA':'Ladakh','LD':'Lakshadweep','PY':'Puducherry'}

def key(value):return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKC',str(value or '')).casefold())
IDS={key(name):code for code,name in NAMES.items()}|{key(code):code for code in NAMES}
IDS.update({key(name):code for name,code in {'Orissa':'OD','Uttaranchal':'UK','Chattisgarh':'CG','Pondicherry':'PY','NCT of Delhi':'DL','NCT Delhi':'DL','New Delhi':'DL','Jammu & Kashmir':'JK','Andaman & Nicobar':'AN','Dadra and Nagar Haveli':'DN','Daman and Diu':'DN'}.items()})
IDS.update({'andamanandnicobar':'AN','uttrakhand':'UK','keralam':'KL'})
def state_id(value):return IDS.get(key(value))
def mode(buy,sell):
    a,b=state_id(buy),state_id(sell)
    return ('intrastate' if a==b else 'interstate') if a and b else None
