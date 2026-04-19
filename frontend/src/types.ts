export type UserRole = "buyer" | "supplier" | "admin";

export type RegisterPayload = {
  username: string;
  email: string;
  password: string;
  role: UserRole;
  company_name?: string;
  inn?: string;
};

export type RegisterResponse = {
  id?: number;
  user_id: number;
  username: string;
  email: string;
  role: UserRole;
  rating?: string | number;
  created_at: string;
};

export type TokenPair = {
  access: string;
  refresh: string;
};

export type JwtClaims = {
  token_type?: string;
  exp?: number;
  iat?: number;
  jti?: string;
  user_id?: number | string;
  [key: string]: unknown;
};

export type AuctionLot = {
  id: number;
  code: string;
  name: string;
  unit: string;
  quantity: string;
};

export type AuctionLotInput = {
  id: number;
  quantity: string;
};

export type CatalogNode = {
  id: number;
  name: string;
  parent_id: number | null;
  has_children: boolean;
  items_count: number;
};

export type CatalogItem = {
  id: number;
  code: string;
  name: string;
  unit: string;
  node_id: number;
  node_name?: string | null;
  parent_node_id?: number | null;
  parent_node_name?: string | null;
  source_id: number | null;
  default_quantity?: string | null;
};

export type CatalogNodesResponse = {
  count: number;
  results: CatalogNode[];
};

export type CatalogItemsResponse = {
  count: number;
  results: CatalogItem[];
};

export type CatalogItemsQuery = {
  q?: string;
  node_id?: number;
  source_id?: number;
  limit?: number;
  offset?: number;
};

export type CatalogNodesQuery = {
  parent_id?: number;
  q?: string;
  limit?: number;
  offset?: number;
};

export type Auction = {
  id: number;
  owner: number;
  title: string;
  description: string;
  start_price: string;
  current_price: string | null;
  start_date: string;
  end_date: string;
  status: "DRAFT" | "PUBLISHED" | "ACTIVE" | "FINISHED" | "CLOSED" | "CANCELED";
  auction_type: string;
  specific?: {
    min_bid_decrement?: string;
  } | null;
  catalog_items?: AuctionLot[];
  lots?: AuctionLot[];
};

export type Bid = {
  id: number;
  auction: number;
  owner: number;
  bid: string;
  comment: string;
};

export type AuctionCreatePayload = {
  title: string;
  description: string;
  start_price: number;
  start_date: string;
  end_date: string;
  auction_type: "reverseenglishauction";
  min_bid_decrement: number;
  lots?: AuctionLotInput[];
};

export type ApiError = {
  error?: string;
  detail?: string;
  [key: string]: unknown;
};

export type CurrentUser = {
  id: number;
  username: string;
  email: string;
  date_joined?: string;
  profile?: {
    role?: UserRole | string | null;
    company_name?: string;
    inn?: string;
    rating?: string | number | null;
  } | null;
};

export type CurrentUserUpdatePayload = {
  username?: string;
  password?: string;
  role?: UserRole;
  company_name?: string;
  inn?: string;
};

export type PartyLookupResponse = {
  inn: string;
  company_name: string;
  full_name?: string;
  ogrn?: string;
  kpp?: string;
};
