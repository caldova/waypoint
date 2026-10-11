import { redirect, type LoaderFunctionArgs } from "react-router";
import { splitLocalePath } from "../i18n/paths";

/** English is unprefixed, so `/en/invoices` redirects to `/invoices`. */
export function loader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  return redirect(`${splitLocalePath(url.pathname).path}${url.search}`);
}
