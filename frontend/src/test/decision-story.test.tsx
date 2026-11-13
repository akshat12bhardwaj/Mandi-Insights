import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render,screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect,it,vi } from 'vitest';
import { DecisionStory,SellingDates } from '../components/DecisionStory';
import type { Market,ScenarioInput,Strategy } from '../lib/intelligence';

const market=(id:string):Market=>({series_id:id,crop:'Onion',state:'S',district:'D',market:id,variety:'Other',grade:'FAQ',source:'datagov',predicted_price:id==='Buy'?1000:1500,last_observed_price:1000,status:'Estimated today',coordinate:{lat:20,lng:75,node:id,precision:'Approximate'}});
const trade:Strategy={id:'one',crop:'Onion',buy:market('Buy'),sell:market('Sell'),quantity_q:100,trips:1,vehicle:'Medium truck',route:{objective:'shortest',km:100,hours:2,basis:'Saved road',origin:'A',destination:'B',transport_cost:3500},routes:[],storage_days:0,warehouse:null,procurement:100000,transport:3500,handling:1800,storage:0,total_cost:105300,sale_revenue:148500,margin:43200,uncertainty_screen:10000,risk_adjusted_margin:33200,sale_price:1500,sale_basis:'Current-day forecast',loss_pct:1,explanation:'Evidence',truck_utilization:1,
 data_quality:{label:'Recent reports · saved road path',maximum_observation_age_days:1,route_evidence:'Road path',recent_price_movement_rs:50},
 decision:{headline:'Buy Onion in Buy · sell in Sell',cards:[{title:'Price spread',value:'₹500/quintal',text:'Observed inputs'},{title:'Transport evidence',value:'100 km',text:'Saved road'},{title:'Data quality',value:'Recent reports',text:'Historical error context'}],alternatives:[{id:'two',crop:'Onion',buy_market:'Alternative buy',sell_market:'Alternative sell',margin:42000,transport:4000,procurement:100000,sale_revenue:147800,score:32000,distance_km:120,procurement_saving:0,transport_saving:500,revenue_advantage:700,margin_difference:1200,score_difference:1200,insight:'Lower freight preserves margin.'}],trade_off:'The alternative adds ₹500 freight.',why_selected:'Adjusted economic value',practical_tie:false,break_even_sale_price:1063.64,what_changes:'Below ₹1,064/quintal this margin disappears.',storage:'Compare selling dates'}};
const form:ScenarioInput={buy_id:'Buy',sell_id:'Sell',quantity:100,vehicle:'Medium truck',handling:18,loss:1,days:7,warehouse_id:'W',route_index:0,future_change:99,future_mode:'scenario'};
function wrap(node:React.ReactNode){return render(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>)}

it('lets users explore an evidence-backed alternative without exposing ranking methodology',async()=>{
 const select=vi.fn();wrap(<DecisionStory strategy={trade} onSelect={select}/>);
 expect(screen.getByRole('region',{name:'Recommended trading journey'})).toBeInTheDocument();
 expect(screen.getByText('100% load use',{exact:false})).toBeInTheDocument();
 await userEvent.click(screen.getByRole('button',{name:'Explore alternative Alternative buy to Alternative sell'}));
 expect(select).toHaveBeenCalledWith('two');
 expect(screen.queryByText('What could change this recommendation?')).not.toBeInTheDocument();
 expect(document.body.textContent).not.toMatch(/\d+% confidence/i);
});

it('uses forecast mode for automatic storage comparisons while preserving manual simulation inputs',async()=>{
 const stored={...trade,storage_days:7,sale_kind:'future_forecast',future_forecast:{model:'persistence',horizon_days:7,target_date:'2026-11-20',price:1500,historical_mae:180,validation_scope:'2017–18'}};
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({rows:[trade,stored],recommended_days:0,recommendation:'Sell immediately',reason:'Extra storage expense reduces benefit.',scope:'Two facilities screened',unavailable:[]})));
 vi.stubGlobal('fetch',fetcher);const use=vi.fn();wrap(<SellingDates form={form} onUse={use}/>);
 await userEvent.click(screen.getByText('Sell now or store?'));
 await userEvent.click(screen.getByRole('button',{name:'Compare selling dates'}));
 expect(await screen.findByText(/Estimated 2026-11-20/)).toBeInTheDocument();
 const body=JSON.parse((fetcher.mock.calls[0] as unknown as [string,RequestInit])[1].body as string);
 expect(body.future_mode).toBe('forecast');expect(form.future_mode).toBe('scenario');
 await userEvent.click(screen.getAllByRole('button',{name:'Use this option'})[1]);
 expect(use).toHaveBeenCalledWith(expect.objectContaining({storage_days:7,sale_kind:'future_forecast'}));
});

it('shows an actionable error when future forecasts are unavailable',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({detail:'No eligible future price is available'}),{status:422})));
 wrap(<SellingDates form={form} onUse={()=>{}}/>);
 await userEvent.click(screen.getByText('Sell now or store?'));await userEvent.click(screen.getByRole('button',{name:'Compare selling dates'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('No eligible future price is available');
 expect(screen.getByRole('button',{name:'Compare selling dates'})).toBeEnabled();
});

it('prevents applying old storage results after the scenario inputs change',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({rows:[trade],recommended_days:0,reason:'No storage expense',scope:'Screened facilities',unavailable:[]}))));
 const use=vi.fn();const client=new QueryClient();
 const view=(inputs:ScenarioInput)=><QueryClientProvider client={client}><SellingDates form={inputs} onUse={use}/></QueryClientProvider>;
 const rendered=render(view(form));
 await userEvent.click(screen.getByText('Sell now or store?'));
 await userEvent.click(screen.getByRole('button',{name:'Compare selling dates'}));
 expect(await screen.findByRole('button',{name:'Use this option'})).toBeVisible();
 rendered.rerender(view({...form,quantity:250}));
 expect(screen.queryByRole('button',{name:'Use this option'})).not.toBeInTheDocument();
 expect(screen.getByText(/Inputs changed/)).toBeVisible();
 await userEvent.click(screen.getByRole('button',{name:'Compare selling dates'}));
 expect(await screen.findByRole('button',{name:'Use this option'})).toBeVisible();
});
