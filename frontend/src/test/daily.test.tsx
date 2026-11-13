import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Today from "../pages/Today";

vi.mock("../components/DailyPriceChart",()=>({default:()=> <div>Observed price trend</div>}));
vi.mock("../components/MapView",()=>({MapView:()=> <div aria-label="Scenario location map"/>}));
const prediction = {
  crop:"Onion",category:"Vegetables",state:"Maharashtra",district:"Nashik",market:"Lasalgaon",variety:"Red",grade:"FAQ",source:"datagov",
  target_date:"2026-11-12",forecast_issue_timestamp:"2026-11-12T09:00:00+05:30",dataset_version:"daily-v1:test",model_version:"daily-persistence-v1",
  status:"prediction_available",predicted_modal_price:2100,last_observed_price:2100,last_observation_date:"2026-11-11",observed_today:null,
  data_freshness:{age_days:1,observations:500,density:.6},historical_error:null,
};
const eligible={series_id:"sid",crop:"Onion",state:"Maharashtra",district:"Nashik",market:"Lasalgaon",variety:"Red",grade:"FAQ"};
let value: Record<string,unknown>, unavailable=false;
let bodies: Record<string,unknown>[];
beforeEach(()=>{
 value={...prediction};unavailable=false;bodies=[];
 vi.stubGlobal("fetch",vi.fn(async(input:string,init?:RequestInit)=>{
  const url=new URL(input,"http://localhost");const path=url.pathname.split("/").at(-1);
  if(unavailable)return new Response(JSON.stringify({detail:"Daily prices not built"}),{status:503});
  if(path==="compare" || path==="trading"){
   const body=JSON.parse(String(init?.body));bodies.push(body);
   return new Response(JSON.stringify({target_date:"2026-11-12",quantity_quintals:body.quantity_quintals,quantity_tonnes:body.quantity_quintals/10,
    summary:"Compare available prices; delivery costs need your assumptions.",comparison_scope:"Regional matching varieties",selected:null,status:"price_comparison",plan:null,scenarios:[],selling_markets:[],analysis_routes:[],analysis_origin:null,analysis_destination:null,
    cheapest_scenario_series_id:null,limitations:["No supported future selling price."],storage:[{warehouse_id:"W",name:"Reported warehouse",facility_type:"warehouse",latitude:20,longitude:75,reference_road_distance_km:12,transport_cost:null,storage_cost:null,scenario_total:null}],
    markets:[{...eligible,age_days:1,predicted_price:2100,comparable:true,landed_cost:null,limitation:"Access distances required."}]}));
  }
  const fixtures:Record<string,unknown>={
   crops:{dataset_version:"test",crops:[{crop:"Onion",category:"Vegetables"},{crop:"Wheat",category:"Cereals and grains"}]},
   locations:[{state:"Maharashtra",district:"Nashik"}],markets:[{...eligible,source:"datagov"}],today:value,history:{points:[]},
   options:{eligible_markets:[eligible],eligible_count:1,destinations:[{node_id:"D:Pune",name:"Pune",state:"Maharashtra",district:"Pune",latitude:18,longitude:74}]},
   weather:{available:false,days:[],used_in_price_model:false,context_reason:"No verified reference"},
  };
  return new Response(JSON.stringify(fixtures[path??""]));
 }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
function show(){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><Today/></QueryClientProvider>);}

describe("daily decision support",()=>{
 it("prioritizes today's estimate and hides methodology behind Details",async()=>{
  show();const card=await screen.findByTestId("daily-forecast");
  await waitFor(()=>expect(card).toHaveTextContent("₹2,100"));
  expect(card).toHaveTextContent("2026-11-12");expect(card).toHaveTextContent("indicative estimate");
  expect(card).not.toHaveTextContent("daily-persistence-v1");expect(card).not.toHaveTextContent("Last observed");
  await userEvent.click(screen.getByText(/Reference market:/));
  for(const label of ["Crop category","Crop","State","District","Market","Variety"]) expect(screen.getByRole("combobox",{name:label})).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"Details"}));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Last observed: ₹2,100");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("daily-persistence-v1");
 });
 it("changes category and requests matching crop",async()=>{
  show();
  await userEvent.selectOptions(await screen.findByRole("combobox",{name:"Crop category"}),"Cereals and grains");
  expect(screen.getByRole("combobox",{name:"Crop"})).toHaveValue("Wheat");
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes("crop=Wheat"))).toBe(true);
 });
 it("withholds stale estimates and offers an eligible alternative",async()=>{
  value={...prediction,status:"stale_unavailable",predicted_modal_price:null};show();
  const card=await screen.findByTestId("daily-forecast");
  await waitFor(()=>expect(card).toHaveTextContent("History is too old"));expect(card).toHaveTextContent("Unavailable");
  expect(await screen.findByRole("button",{name:"Lasalgaon"})).toBeInTheDocument();
  expect(card).not.toHaveTextContent("₹2,100");
 });
 it("keeps actual prices separate from predictions",async()=>{
  value={...prediction,observed_today:2400};show();const card=await screen.findByTestId("daily-forecast");
  await waitFor(()=>expect(card).toHaveTextContent("Reported today: ₹2,400"));expect(card).toHaveTextContent("Kept separate");
 });
 it("applies quantity and transport inputs only after Compare options",async()=>{
  show();await screen.findByRole("button",{name:"Lasalgaon"});const before=bodies.length;
  const quantity=screen.getByRole("spinbutton",{name:"Quantity (quintals)"});
  await userEvent.clear(quantity);await userEvent.type(quantity,"20");
  await userEvent.selectOptions(screen.getByRole("combobox",{name:"Destination reference"}),"D:Pune");
  expect(bodies).toHaveLength(before);
  await userEvent.click(screen.getByRole("button",{name:"Compare options"}));
  await waitFor(()=>expect(bodies.at(-1)).toMatchObject({quantity_quintals:20,destination:"D:Pune"}));
 });
 it("does not turn warehouse candidates into verified storage recommendations",async()=>{
  show();await screen.findByRole("button",{name:"Lasalgaon"});await userEvent.click(screen.getByRole("tab",{name:"Storage Analysis"}));
  const panel=screen.getByRole("tabpanel");expect(panel).toHaveTextContent("Reported warehouse");
  expect(panel).toHaveTextContent("Suitability and available capacity: unknown");expect(panel).toHaveTextContent("tariff unknown");
  expect(panel).toHaveTextContent("No storage-for-profit recommendation");
 });
 it("supports keyboard tab navigation",async()=>{
  show();const buy=await screen.findByRole("tab",{name:"Today's Decision"});buy.focus();await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab",{name:"Route Analysis"})).toHaveAttribute("aria-selected","true");
 });
 it("keeps one scenario and quantity across all three primary tabs",async()=>{
  show();await screen.findByRole("button",{name:"Lasalgaon"});
  const quantity=screen.getByRole("spinbutton",{name:"Quantity (quintals)"});
  await userEvent.clear(quantity);await userEvent.type(quantity,"25");
  await waitFor(()=>expect(bodies.at(-1)).toMatchObject({quantity_quintals:25}),{timeout:2000});
  const requests=bodies.length;
  await userEvent.click(screen.getByRole("tab",{name:"Route Analysis"}));
  expect(screen.getByRole("spinbutton",{name:"Quantity (quintals)"})).toHaveValue(25);
  await userEvent.click(screen.getByRole("tab",{name:"Storage Analysis"}));
  expect(screen.getByRole("spinbutton",{name:"Quantity (quintals)"})).toHaveValue(25);
  expect(bodies).toHaveLength(requests);
  expect(screen.getAllByRole("tab")).toHaveLength(3);
 });
 it("offers owned-produce sale objectives without inventing acquisition costs",async()=>{
  show();await screen.findByRole("button",{name:"Lasalgaon"});
  await userEvent.selectOptions(screen.getByRole("combobox",{name:"Decision objective"}),"Sell now");
  await waitFor(()=>expect(bodies.at(-1)).toMatchObject({objective:"sell_now",acquisition_rs_per_quintal:null}),{timeout:2000});
 });
 it("handles an unavailable backend",async()=>{
  unavailable=true;show();expect(await screen.findByRole("alert")).toHaveTextContent("Daily prices not built");
 });
});
