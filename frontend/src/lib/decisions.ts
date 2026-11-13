import { useQuery } from "@tanstack/react-query";

export interface EligibleMarket { series_id:string; crop:string; state:string; district:string; market:string; variety:string; grade:string }
export interface Destination { node_id:string; name:string; state:string; district:string; latitude:number; longitude:number }
export interface DecisionOptions { eligible_markets:EligibleMarket[]; eligible_count:number; destinations:Destination[]; target_date:string }
export interface CostAssumptions {
  mode:"freight"|"fuel"|"per_km"; freight_rs_per_tonne_km:number|null; fuel_rs_per_litre:number|null;
  vehicle_type?:string; load_capacity_quintals?:number|null; rs_per_vehicle_km?:number|null; toll_rs_per_trip?:number;
  vehicle_km_per_litre:number|null; fixed_trip_rs:number; handling_rs_per_quintal:number;
  destination_access_km:number|null; market_access_km:Record<string,number>; warehouse_access_km:Record<string,number>;
}
export interface DecisionRequest {
  series_id:string; quantity_quintals:number; destination:string|null; region:"state"|"all";
  transport:CostAssumptions; storage_days:number; storage_rs_per_tonne_month:number|null;
  objective?:"buy_now"|"sell_now"|"buy_deliver"|"buy_store_sell"|"compare_all";
  preferred_sell_series_id?:string|null; acquisition_rs_per_quintal?:number|null; max_transport_km?:number|null; warehouse_id?:string|null;
}
export interface RouteCost { objective:"shortest"|"fastest"; road_distance_km:number; travel_time_h:number; transport_cost:number|null; fuel_expense:number|null; cost_per_quintal:number|null; trips?:number|null; objectives?:string[]; reason?:string; total_distance_km?:number|null }
export interface MarketCost extends EligibleMarket {
  predicted_price:number; age_days:number; comparable:boolean; reference_node:string|null;
  procurement_cost:number; landed_cost:number|null; landed_per_quintal:number|null; best_route:string|null; routes:RouteCost[]; limitation:string;
}
export interface StorageCost { warehouse_id:string; name:string; facility_type:string; latitude:number; longitude:number;
  reference_road_distance_km:number; transport_cost:number|null; storage_cost:number|null; scenario_total:number|null;
  storage_cost_basis:string; suitability:"unknown"; available_capacity_t:null; recommendation:"candidate_only";
  source?:string|null; source_update_date?:string|null; operator?:string|null; nominal_capacity_t?:number|null; coordinate_status?:string; destination_to_facility_reference_km?:number|null; distance_to_destination_km?:number|null; reason?:string;
}
export interface DecisionResult { target_date:string; quantity_quintals:number; quantity_tonnes:number; markets:MarketCost[]; storage:StorageCost[];
  selected:MarketCost|null; comparison_scope:string; summary:string; status:string; cheapest_scenario_series_id:string|null; limitations:string[];
}
export interface TradingScenario { scenario_id:string; kind:string; buy:EligibleMarket|null; sell:EligibleMarket|null; route_origin:string|null; route_destination:string|null;
 route:RouteCost|null; routes:RouteCost[]; procurement_cost:number|null; transport_cost:number|null; handling_cost:number; total_cost:number|null;
 sale_revenue:number|null; net_sale_proceeds:number|null; estimated_margin:number|null; complete:boolean; missing:string[]; ranking:string; explanation:string;
}
export interface TradingResult extends DecisionResult {objective:string; selling_markets:(EligibleMarket & {predicted_price:number;age_days:number})[]; scenarios:TradingScenario[]; plan:TradingScenario|null; uncertainty:{mae_rs_per_quintal:number|null; method:string;calibrated:boolean}; warehouse_selection:string|null;analysis_routes:RouteCost[];analysis_origin:string|null;analysis_destination:string|null;location_evidence?:Record<string,{meaning:string;reference_coordinate:{latitude:number;longitude:number};road_access_coordinate:{latitude:number;longitude:number;straight_line_gap_km:number}|null}|null> }
export interface DecisionWeather { available:boolean; stale?:boolean; used_in_price_model:false; context_reason:string|null;
  heavy_rain_days?:{date:string;rain_mm:number}[];
  coverage:string; reason:string|null; days:{ date:string; rain_mm:number|null; tmax_c:number|null; rain_probability_pct:number|null; humidity_mean_pct?:number|null; wind_max_kmh?:number|null }[];
}
async function request<T>(path:string, body?:DecisionRequest):Promise<T> {
  const response=await fetch(`/api/v3/decisions/${path}`,body ? {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)} : undefined);
  if(!response.ok){const error=await response.json().catch(()=>({})); throw new Error(typeof error.detail==="string"?error.detail:"The comparison is unavailable. Check the inputs and try again.");}
  return response.json();
}
export const useDecisionOptions=(crop:string)=>useQuery<DecisionOptions,Error>({queryKey:["decision-options",crop],enabled:!!crop,staleTime:60000,retry:false,queryFn:()=>request(`options?${new URLSearchParams({crop})}`)});
export const useDecision=(value:DecisionRequest)=>useQuery<DecisionResult,Error>({queryKey:["decision-compare",value],enabled:!!value.series_id,staleTime:60000,retry:false,queryFn:()=>request("compare",value)});
export const useTrading=(value:DecisionRequest)=>useQuery<TradingResult,Error>({queryKey:["trading-v2",value],enabled:!!value.series_id,staleTime:60000,refetchInterval:60000,retry:false,queryFn:()=>request("trading",value)});
export const useDecisionWeather=(series_id:string,warehouse_id?:string)=>useQuery<DecisionWeather,Error>({queryKey:["decision-weather-v2",series_id,warehouse_id],enabled:!!series_id,staleTime:600000,retry:false,queryFn:()=>request(`weather?${new URLSearchParams({series_id,...(warehouse_id?{warehouse_id}:{})})}`)});
