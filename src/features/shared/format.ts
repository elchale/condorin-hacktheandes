/** 51936282808 to +51 936 282 808. Other countries keep their digits after the plus sign. */
export function formatPhone(phone: string) {
  const peru = /^51(9\d{2})(\d{3})(\d{3})$/.exec(phone);
  return peru ? `+51 ${peru[1]} ${peru[2]} ${peru[3]}` : `+${phone}`;
}

export const dragas = (n: number) => (n === 1 ? "1 posible draga" : `${n} posibles dragas`);
