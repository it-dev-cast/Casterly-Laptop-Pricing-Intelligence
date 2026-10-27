"""Explicit live provider verification with four public hardware identities; never mocks or customer rows.
Run from backend: python ../scripts/verify_live_research.py
Keys are read from server environment / existing project env files. No DB writes.
"""
from pathlib import Path
import json
import sys
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env',override=False)
load_dotenv(ROOT/'backend/.env',override=False)
from app.procurement.providers import default_provider, PROVIDERS, get_provider, queries_for, ProviderError
from app.procurement.identify import identify
from app.procurement.extraction import to_candidate,confirmed_offer,source_timestamp
from app.procurement.engine import Group, Obs, price_group
from app.procurement.rules import default_rules

cases=[('Dell laptop',{'model':'Dell Latitude 5430','cpu':'i5-1245U','ram':'16GB','storage':'256GB','grade':'B'}),
       ('Samsung phone',{'model':'Samsung Galaxy A54 5G 8GB/128GB','grade':'B'}),
       ('Intel Xeon',{'model':'XEON GOLD 6130','category_hint':'PM-CPU','grade':'B'}),
       ('DDR4 ECC RAM',{'description':'Samsung 16GB DDR4 2400 ECC RDIMM','category_hint':'RC-RAM','grade':'B'})]
first=default_provider()
names=([first]+[n for n in PROVIDERS if n!=first and get_provider(n).configured()]) if first else []
report={'run_at':datetime.now(timezone.utc).isoformat(),'live_requests_attempted':0,
        'status':'BLOCKED' if not names else 'EXECUTED','required_configuration':None if names else 'CLPI_BRAVE_API_KEY or CLPI_TAVILY_API_KEY',
        'note':'Real requests only. An empty/ambiguous result is not a verified price. No customer asset lists or credentials are exported.', 'cases':[]}
rules=default_rules()
for label,row in cases:
    ident=identify(row);records=[];errors=[];observations=[];queries=queries_for(ident.category,ident.spec,ident.label,2)
    for name in names:
        for query in queries:
            report['live_requests_attempted']+=1
            try:hits=get_provider(name).search(query,count=5,country='IN')
            except ProviderError as e:
                errors.append({'provider':name,'query':query,'error':str(e)});continue
            records.append({'provider':name,'query':query,'http_provider_success':True,'returned_hits':len(hits)})
            for hit in hits:
                candidate=to_candidate(hit,ident.category,ident.spec)
                amount,confirmation=confirmed_offer(hit,ident.category,ident.spec)
                valid=(candidate.reason in (None,"no price shown in the provider's result text") and amount is not None
                       and candidate.match_quality=='identical' and candidate.condition in ('used','refurbished'))
                source=source_timestamp(hit);when=datetime.now(timezone.utc)
                records.append({'provider':name,'title':hit.title,'source_url':hit.url,'observed_price':str(amount) if valid else None,
                    'candidate_price':str(candidate.price) if candidate.price is not None else None,
                    'verified':valid,'source_type':candidate.price_type,'source_timestamp':source.isoformat() if source else None,
                    'research_timestamp':when.isoformat(),'confirmation':confirmation,'rejection':candidate.reason,
                    'match_quality':candidate.match_quality,'condition':candidate.condition})
                if valid:
                    observations.append(Obs(len(observations)+1,amount,'INR','unknown',candidate.price_type,'identical',source or when,
                      candidate.domain,.5,'verified',url=hit.url,title=hit.title,condition=candidate.condition,
                      research_mode='live_search_confirmed',source_timestamp=source.isoformat() if source else None))
        if observations:break
    variant='server_ram_'+ident.spec['ddr'].lower() if ident.category=='server_ram' and ident.spec.get('ddr') else 'server_cpu_xeon' if ident.category=='server_cpu' else None
    group=Group(ident.category,'B',1,risk_flags=ident.risk_flags,identify_confidence=ident.confidence,policy_variant=variant)
    calculation=price_group(group,observations,rules,datetime.now(timezone.utc))
    report['cases'].append({'case':label,'status':'BLOCKED' if not names else 'PRICED' if observations else 'NEEDS_REVIEW',
        'product':ident.label,'specifications':ident.spec,'requests_and_results':records,'errors':errors,'calculation':calculation})
output=ROOT/'docs/MARKET_LIVE_RESEARCH_RESULTS.json'
output.write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
print(f"Live verification: {report['status']}; requests attempted: {report['live_requests_attempted']}; report: {output.name}")
